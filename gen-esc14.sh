#!/bin/sh
DEVICE="MAX78000"
TARGET="sdk-temp"
COMMON_ARGS="--device $DEVICE --compact-data --mexpress --timer 0 --display-checkpoint"
./ai8xize.py --verbose --log --test-dir $TARGET --prefix esc14 --checkpoint-file trained/esc14v0-combo-best-qat8-q.pth.tar --config-file networks/esc14-hwc.yaml --softmax $COMMON_ARGS "$@"

