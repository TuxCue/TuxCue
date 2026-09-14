#!/bin/sh
set -eu
cd /build
mkdir -p ffmpeg-source
tar -xJf inputs/ffmpeg -C ffmpeg-source --strip-components=1
cd ffmpeg-source
# Keep audio import/editing support, without network protocols or external video codecs.
./configure --prefix=/opt/tuxcue-media --disable-autodetect --disable-network \
  --disable-doc --disable-debug --disable-ffplay --disable-avdevice \
  --disable-shared --enable-static --disable-hwaccels \
  --disable-encoders --enable-encoder=pcm_s16le,libmp3lame --enable-libmp3lame \
  --disable-muxers --enable-muxer=wav,mp3,null \
  --disable-demuxers --enable-demuxer=mp3,wav,flac,ogg,mov,aac,aiff,asf \
  --disable-protocols --enable-protocol=file,pipe \
  --disable-filters --enable-filter=aresample,anull,atrim,asetpts,volume,afade,apad,alimiter,aformat,abuffer,abuffersink
make -j"${TUXCUE_BUILD_JOBS:-4}"
make install
cp ffbuild/config.mak /build/ffmpeg-config.mak
cp config.h /build/ffmpeg-config.h
