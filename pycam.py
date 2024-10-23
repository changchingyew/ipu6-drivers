#!/usr/bin/env python3

import cv2
from fcntl import ioctl
import mmap
import numpy as np
import os
import struct
import v4l2
import sys

NUM_BUFFERS = 4
NUM_PLANES = 8

# https://github.com/andre-wojtowicz/yuv422-display/blob/e22fb1a57e40137599188f3f9dc7d41782b23720/python/yuv422_display.py#L15
def uyvy_to_yuv(d, h, w):
    U  = d[0::4]
    Y1 = d[1::4]
    V  = d[2::4]
    Y2 = d[3::4]

    UV = np.empty((h * w), dtype=np.uint8)
    YY = np.empty((h * w), dtype=np.uint8)

    UV[0::2] = U
    UV[1::2] = V
    YY[0::2] = Y1
    YY[1::2] = Y2

    UV = UV.reshape((h, w))
    YY = YY.reshape((h, w))

    yuv = cv2.merge([UV, YY])

    return yuv

class Camera(object):
    def __init__(self, device_name):
        self.device_name = device_name
        self.open_device()
        self.init_device()
        self.win = cv2.namedWindow(self.device_name, cv2.WINDOW_NORMAL)
        self.fullscreen = False
        self.resize = True
        if self.fullscreen:
            cv2.setWindowProperty(self.device_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        self.planes = None
        self.stop = False

    def open_device(self):
        self.fd = os.open(self.device_name, os.O_RDWR, 0)

    def init_device(self):
        cap = v4l2.v4l2_capability()
        fmt = v4l2.v4l2_format()
        n = 0
        
        ioctl(self.fd, v4l2.VIDIOC_QUERYCAP, cap)
        
        if not (cap.capabilities & v4l2.V4L2_CAP_VIDEO_CAPTURE_MPLANE):
            raise Exception("{} is not a video capture device".format(self.device_name))

        fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        ioctl(self.fd, v4l2.VIDIOC_G_FMT, fmt)

        print(f"pixelformat {v4l2.v4l2_fourcc2str(fmt.fmt.pix_mp.pixelformat)}, width {fmt.fmt.pix_mp.width}, height {fmt.fmt.pix_mp.height}")
        self.fmt = fmt.fmt.pix_mp.pixelformat
        self.width = fmt.fmt.pix_mp.width
        self.height = fmt.fmt.pix_mp.height
        self.init_mmap()
    
    def init_mmap(self):
        req = v4l2.v4l2_requestbuffers()

        self.planes = ((NUM_PLANES * NUM_BUFFERS) * v4l2.v4l2_plane)()
        
        req.count = NUM_BUFFERS
        req.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        req.memory = v4l2.V4L2_MEMORY_MMAP
        
        try:
            ioctl(self.fd, v4l2.VIDIOC_REQBUFS, req)
        except Exception:
            raise Exception("video buffer request failed")
        
        if req.count < 2:
            raise Exception("Insufficient buffer memory on {}".format(self.device_name))

        self.buffers = []
        for i in range(req.count):
            planes = (NUM_PLANES * v4l2.v4l2_plane)()
            buf = v4l2.v4l2_buffer()
            buf.index = i
            buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
            buf.memory = v4l2.V4L2_MEMORY_MMAP
            buf.m.planes = planes
            buf.length = NUM_PLANES
            
            ioctl(self.fd, v4l2.VIDIOC_QUERYBUF, buf)
            self.num_planes = buf.length

            for j in range(self.num_planes):
                p = self.planes[(i*NUM_BUFFERS+j)]
                p.length = planes[j].length
                print(f"mmap buffer {i}[{j}], len {p.length}, offs {planes[j].m.mem_offset}")
                buf.buffer = mmap.mmap(self.fd, p.length, mmap.PROT_READ, mmap.MAP_SHARED, offset=planes[j].m.mem_offset)
                self.buffers.append(buf)

    def start_capturing(self):
        for buf in self.buffers:
            ioctl(self.fd, v4l2.VIDIOC_QBUF, buf)
        video_type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        ioctl(self.fd, v4l2.VIDIOC_STREAMON, struct.pack('I', video_type))
        self.main_loop()
    
    def process_image(self, buf):
        video_buffer = self.buffers[buf.index].buffer
        bytesused = buf.m.planes[0].bytesused
        if bytesused == 0:
            return
        video_buffer.seek(0)
        data = video_buffer.read(bytesused)
        try:
            if self.fmt == v4l2.V4L2_PIX_FMT_UYVY:
                data = np.frombuffer(data, dtype=np.uint8)
                if self.resize:
                    data = data[self.height//4*self.width*2:self.height*3//4*self.width*2]
                    height = self.height//2
                else:
                    height = self.height
                image_uyvy = uyvy_to_yuv(data, height, self.width)
                image_bgr = cv2.cvtColor(image_uyvy, cv2.COLOR_YUV2BGR_UYVY)
            elif self.fmt == v4l2.V4L2_PIX_FMT_Y10:
                data = np.frombuffer(data, dtype=np.uint16)
                image_gray = np.reshape(data, (self.height, self.width))
                image_bgr = cv2.cvtColor(image_gray, cv2.COLOR_GRAY2BGR)
            else:
                print("Unexpected pixel format")
                stop = True
            cv2.imshow(self.device_name, image_bgr)
            k = cv2.waitKey(1)
            if k == ord('q'):
                self.stop = True
            elif k == 27:
                self.stop = True
        except KeyboardInterrupt as e:
            self.stop = True
        except Exception as e:
            print("Error", e)
            self.stop = True


    def main_loop(self):
        x = 0
        while not self.stop:
            buf = self.buffers[x % NUM_BUFFERS]
            x += 1
            ioctl(self.fd, v4l2.VIDIOC_DQBUF, buf)
            self.process_image(buf)
            ioctl(self.fd, v4l2.VIDIOC_QBUF, buf)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        dev = sys.argv[1]
    else:
        dev = "/dev/video0"
    cam = Camera(dev)
    cam.start_capturing()