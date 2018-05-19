#!/bin/bash

pbrt $1.pbrt
imgtool convert $1.exr $1.png
# cp $1.pbrt $1.pbrt.backup
open $1.png