#!/bin/sh
#SOURCE="../ai8x-training/logs/2021.04.13-134340_ESC14_musicspeech_net14v0_reordered_combomerged_shift_aug5_NoAugTest_schESC20-1_lr1e-3_batch64_878684_100epochs"
SOURCE="../ai8x-training/logs/2021.04.13-170026"
SOURCE="../ai8x-training/logs/2021.04.13-200228"
FILE="esc14v0-combo-best-qat8-q.pth.tar"
./quantize.py "$SOURCE/best.pth.tar" "$SOURCE/$FILE" --device MAX78000 -v "$@"
cp "$SOURCE/$FILE" "trained/$FILE"
