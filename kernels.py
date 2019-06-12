###################################################################################################
# Copyright (C) 2018-2019 Maxim Integrated Products, Inc. All Rights Reserved.
#
# Maxim Confidential
#
# Written by RM
###################################################################################################
"""
Kernel related functions
"""
import math
import sys
import numpy as np
from tornadocnn import MASK_WIDTH, MAX_CHANNELS, P_SHARED, BIAS_SIZE, P_NUMGROUPS, C_GROUP_OFFS, \
    P_NUMPRO, C_MRAM_BASE
from utils import argmin, ffs, fls


_INVALID_VALUE = -(2**63)


def print_map(layers, kmap):
    """
    Print map of all used kernels in kernel map `kmap`. `layers` describes the number of layers
    in the network and is used to align the map.
    """
    width = int(math.log10(layers)) + 1
    if width > 1:
        width += 1  # Add space if wider than a single character

    print('-' * kmap.shape[1] * width)
    for row in range(kmap.shape[0]):
        for col in range(kmap.shape[1]):
            val = kmap[row][col]
            if val == _INVALID_VALUE:
                val = 'X'
            print('{:>{w}}'.format(val, w=width), end='')
        print('')
    print('-' * kmap.shape[1] * width)


def load(verbose, embedded_code, apb, layers, kernel, _kernel_size, processor_map, chan,
         debug=False):
    """
    Stack `kernel` values and write them to C code (for `embedded_code` if `True` or
    RTL simulation). The output is written to the `apb` object.
    Input is configured with `kernel_size`, `layers`, `processor_map` and `chan`.
    This function returns the kernel offsets and the kernel lengths for all layers.
    """
    # Kernels: Stack kernels; write only the kernels needed
    chan_kern_max = [0] * MAX_CHANNELS
    kern_offs = [0] * layers
    kern_len = [0] * layers
    kernel_map = np.full((MAX_CHANNELS, MASK_WIDTH), _INVALID_VALUE, dtype=np.int64)
    if embedded_code:
        # There are four 32-bit words per 9-byte kernel.
        # The value map is initialized with zeros so we can later ignore unused entries and use
        # memcpy() on initialized and uninitialized data.
        kernel_values = np.zeros((MAX_CHANNELS, MASK_WIDTH * 4), dtype=np.int64)

    for ll in range(layers):
        first_channel = ffs(processor_map[ll])
        last_channel = fls(processor_map[ll])
        ch = 0
        for c in range(first_channel, last_channel+1):
            if (processor_map[ll] >> c) & 1 == 0:
                # Unused processor
                continue
            # Get highest offset for all used channels
            kern_offs[ll] = max(chan_kern_max[c], kern_offs[ll])

        # Determine the number of kernels that need to be programmed. Since each instance
        # spans 4 processors, kernels for all instances that have a single processor enabled
        # need to be written, i.e. round down the first. The last does not need to be rounded
        # up because hardware takes care of it.
        next_layer_map = processor_map[ll+1]
        kern_len[ll] = 1 + fls(next_layer_map) - (ffs(next_layer_map) & ~(P_SHARED-1))
        # We don't have to use dummy columns if there's space available on the left
        kern_offs[ll] = max(0, kern_offs[ll] - (ffs(next_layer_map) % P_SHARED))
        # The kernel offset needs to start at a multiple of 4.
        kern_offs[ll] = (kern_offs[ll] + P_SHARED-1) & ~(P_SHARED-1)
        if kern_offs[ll] + kern_len[ll] > MASK_WIDTH:
            print(f'\nKernel memory exceeded at layer {ll}; offset: {kern_offs[ll]}, '
                  f'needed: {kern_len[ll]}.')
            print('\nKernel map so far:')
            print_map(layers, kernel_map)
            sys.exit(1)

        for c in range(first_channel, last_channel+1):
            if (processor_map[ll] >> c) & 1 == 0:
                # Unused processor
                continue
            # Start at the first used instance
            this_map = next_layer_map >> ffs(next_layer_map)
            coffs = ffs(next_layer_map) % P_SHARED
            for col in range(chan[ll+1]):
                # Skip over unused bits in the processor map
                while this_map & 1 == 0:
                    assert this_map != 0
                    coffs += 1
                    this_map >>= 1
                this_map >>= 1

                k = kernel[ll][ch + col*chan[ll]].flatten()
                if debug:
                    print(f'Channel {c} Layer {ll} m{col}/{chan[ll+1]-1}: {k}')
                if not embedded_code:
                    # Write in-line
                    apb.write_kern(ll, c, kern_offs[ll] + col + coffs, k)
                else:
                    # Store for later
                    offs = 4 * (kern_offs[ll] + col + coffs)  # Word offset
                    kernel_values[c][offs] = k[0] & 0xff
                    kernel_values[c][offs + 1] = (k[1] & 0xff) << 24 | (k[2] & 0xff) << 16 | \
                        (k[3] & 0xff) << 8 | k[4] & 0xff
                    kernel_values[c][offs + 2] = (k[5] & 0xff) << 24 | (k[6] & 0xff) << 16 | \
                        (k[7] & 0xff) << 8 | k[8] & 0xff
                    kernel_values[c][offs + 3] = 0

                # Update kernel map
                assert kernel_map[c][kern_offs[ll] + col + coffs] == _INVALID_VALUE
                kernel_map[c][kern_offs[ll] + col + coffs] = ll

            assert kern_len[ll] == coffs + chan[ll+1]
            chan_kern_max[c] = kern_offs[ll] + kern_len[ll]
            ch += 1

    if verbose:
        print('\nKernel map:')
        print_map(layers, kernel_map)

    if embedded_code:
        # Write kernels, combining layers and processors where possible to reduce the number
        # of constants and calls to memcpy.
        apb.output('// Kernels:\n')

        # First, define the weights (will move to header file)
        p = 0
        while p < MAX_CHANNELS:
            if chan_kern_max[p] > 0:
                start = p
                while (
                        chan_kern_max[p] == MASK_WIDTH and p+1 < MAX_CHANNELS and
                        chan_kern_max[p+1] and (start & ~(P_NUMPRO-1)) == (p+1 & ~(P_NUMPRO-1))
                ):
                    p += 1
                # Combine multiple channels into one define
                k = None
                for i in range(start, p + 1):
                    if k is None:
                        k = kernel_values[i][:chan_kern_max[i] * 4]
                    else:
                        k = np.concatenate((k, kernel_values[i][:chan_kern_max[i] * 4]))

                apb.output_define(k, f'KERNELS_{start}', '0x%08x', 8)
            p += 1

        # Second, initialize static const variables as source for memcpy
        p = 0
        while p < MAX_CHANNELS:
            if chan_kern_max[p] > 0:
                span = chan_kern_max[p]
                start = p
                while (
                        chan_kern_max[p] == MASK_WIDTH and p+1 < MAX_CHANNELS and
                        chan_kern_max[p+1] and (start & ~(P_NUMPRO-1)) == (p+1 & ~(P_NUMPRO-1))
                ):
                    p += 1
                    span += chan_kern_max[p]
                apb.output(f'static const uint32_t kernels_{start}[{span * 4}] = '
                           f'KERNELS_{start};\n')
            p += 1
        apb.output('\n')

        # Generate code to load the weights using memcpy
        apb.output('void load_kernels(void)\n{\n')
        p = 0
        while p < MAX_CHANNELS:
            if chan_kern_max[p] > 0:
                span = chan_kern_max[p]
                start = p
                addr = apb.apb_base + C_GROUP_OFFS * (p // P_NUMPRO) \
                    + C_MRAM_BASE + (p % P_NUMPRO) * MASK_WIDTH * 16
                while (
                        chan_kern_max[p] == MASK_WIDTH and p+1 < MAX_CHANNELS and
                        chan_kern_max[p+1] and (start & ~(P_NUMPRO-1)) == (p+1 & ~(P_NUMPRO-1))
                ):
                    p += 1
                    span += chan_kern_max[p]
                apb.output(f'  memcpy((uint32_t *) 0x{addr:08x}, kernels_{start}, '
                           f'sizeof(uint32_t) * {span * 4});\n')
            p += 1

        apb.output('}\n\n')

    return kern_offs, kern_len


def load_bias(verbose, apb, layers,  # pylint: disable=unused-argument
              bias, group_map, chan, debug):  # pylint: disable=unused-argument
    """
    Write `bias` values for the network to C code.
    """
    # Bias: Each group has one bias memory (size BIAS_SIZE bytes). Use only the bias memory in
    # one selected group for the layer, and only if the layer uses a bias. Keep track of the
    # offsets so they can be programmed into the mask count register later.
    group_bias_max = [0] * P_NUMGROUPS
    bias_offs = [None] * layers
    bias_group = [None] * layers
    for ll in range(layers):
        if bias[ll] is None:
            continue
        if len(bias[ll]) != chan[ll+1]:
            print(f'Layer {ll}: output channel count {chan[ll+1]} does not match the number '
                  f'of bias values {len(bias[ll])}.')
            sys.exit(1)
        # Pick the group with the least amount of data in it
        group = argmin(group_bias_max[t] for t in group_map[ll])
        if group_bias_max[group] + chan[ll+1] > BIAS_SIZE:
            print(f'Layer {ll}: bias memory capacity exceeded - available groups: '
                  f'{group_map[ll]}, used so far: {group_bias_max}, needed: {chan[ll+1]}.')
            sys.exit(1)
        bias_group[ll] = group
        bias_offs[ll] = group_bias_max[group]
        # Each layer has output_channel number of bias values
        for i in range(chan[ll+1]):
            apb.write_bias(group, bias_offs[ll] + i, bias[ll][i])
        group_bias_max[group] += chan[ll+1]

    return bias_offs, bias_group, group_bias_max