FROM ubuntu:22.04@sha256:829f6df217bcbae2b371026e81711d1a787c61b2967ad09d015063663ebafbf7
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1
RUN sed -n 's/^deb /deb-src /p' /etc/apt/sources.list > /etc/apt/sources.list.d/tuxcue-sources.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev python3-gi python3-xlib \
    gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 gir1.2-gstreamer-1.0 \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-pulseaudio \
    pulseaudio-utils binutils patchelf ca-certificates curl squashfs-tools \
    desktop-file-utils libfuse2 file build-essential pkg-config nasm libmp3lame-dev dpkg-dev
WORKDIR /build
COPY packaging/inputs.json packaging/fetch_inputs.py packaging/build_ffmpeg.sh /build/packaging/
RUN python3 packaging/fetch_inputs.py && sh packaging/build_ffmpeg.sh
ENV PATH=/opt/tuxcue-media/bin:/opt/venv/bin:$PATH
RUN python3 -m venv --system-site-packages /opt/venv
COPY requirements.lock requirements-build.lock /build/
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade --no-deps --require-hashes -r requirements-build.lock \
    && /opt/venv/bin/pip install --no-cache-dir --ignore-installed --require-hashes -r requirements.lock
RUN apt-get install -y --no-install-recommends python3-cairo && python -m pip check
COPY packaging /build/packaging
COPY soundboard /build/soundboard
COPY tests /build/tests
COPY LICENSE THIRD_PARTY_NOTICES.md /build/
RUN python -m unittest discover -s tests -v
COPY frontend/dist /build/frontend/dist
RUN pyinstaller --noconfirm --clean packaging/tuxcue.spec
RUN mkdir -p AppDir/usr/bin && cp -a dist/tuxcue/. AppDir/usr/bin/ \
    && cp packaging/AppRun AppDir/AppRun && chmod +x AppDir/AppRun \
    && cp packaging/tuxcue.desktop AppDir/tuxcue.desktop \
    && cp frontend/dist/tuxcue-logo.png AppDir/tuxcue.png && ln -s tuxcue.png AppDir/.DirIcon \
    && desktop-file-validate AppDir/tuxcue.desktop && AppDir/AppRun --self-check
RUN python packaging/collect_licenses.py && python packaging/check_appdir.py AppDir
RUN chmod +x inputs/appimagetool inputs/runtime && inputs/appimagetool --appimage-extract > /dev/null
RUN mkdir /output && VERSION=$(python -c 'from soundboard import __version__; print(__version__)') \
    && ARCH=x86_64 squashfs-root/AppRun --runtime-file inputs/runtime --no-appstream --comp zstd AppDir /output/TuxCue-$VERSION-x86_64.AppImage \
    && tar -cJf /output/TuxCue-$VERSION-third-party-sources.tar.xz -C /build release-sources \
    && cp AppDir/usr/bin/_internal/licenses/components.json /output/COMPONENTS.json
