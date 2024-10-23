#!/bin/bash -x
set -e

if [ ${UID} -eq 0 ]; then
echo 'module intel_ipu6_isys =plmf' > /sys/kernel/debug/dynamic_debug/control
fi

mux="${1:-a}"
mux_dev=$(media-ctl -e "ISX031 mux ${mux}")
cap_dev="/dev/video-isx031-${mux}"
if [[ "${mux_dev}" == *"not found" ]]; then
    exit 1
fi
echo "Mux: ${mux_dev}, Cap: ${cap_dev}"

v4l2-ctl -d ${mux_dev} -c v4l2_cid_link_freq=1
v4l2-ctl -d ${cap_dev} --set-fmt-video=width=1920,height=1536,pixelformat=UYVY

if [ ${UID} -eq 0 ]; then
    sudo -u intel DISPLAY=:0 xhost +
    export DISPLAY=:0
fi
exec ./pycam.py "${cap_dev}"

# rm -Rf frames
# mkdir -p frames
# gst-launch-1.0  -e -v  v4l2src device=${cap_dev} ! 'video/x-raw, width=1920, height=1536, format=YUY2, pixel-aspect-ratio=1/1, framerate=60/1' \
#     ! multifilesink location=frames/frame_%04d.yuy2

#! glupload ! glcolorconvert ! glimagesink


