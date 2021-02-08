#!/bin/sh
DEVICE="MAX78000"
TARGET="sdk/Examples/$DEVICE/CNN"
COMMON_ARGS="--device $DEVICE --compact-data --mexpress --timer 0 --display-checkpoint"
./ai8xize.py --verbose --log --test-dir $TARGET --prefix esc20 --checkpoint-file trained/ai85-esc20_v3-qat8.pth.tar --config-file networks/esc20-net32-hwc.yaml --softmax $COMMON_ARGS "$@"

