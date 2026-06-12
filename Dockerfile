# me_pdf Hermes runtime extension
#
# Keep the current Hermes runtime as the base. This Dockerfile only adds the
# PDF remediation dependencies required by the orchestrator.

FROM nousresearch/hermes-agent:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
ENV VERAPDF_VERSION=1.30.1
ENV VERAPDF_ARLINGTON_BIN=/opt/verapdf/arlington-pdf-model-checker
ENV VERAPDF_GREENFIELD_BIN=/opt/verapdf-greenfield/verapdf
ENV VERAPDF_PROFILE_SOURCE=/opt/veraPDF-validation-profiles-integration

# Debian Trixie-compatible packages from the legacy remediation image.
# Excluded intentionally:
# - software-properties-common: Ubuntu repo helper; not needed on Debian Trixie.
# - fonts-ibm-plex: not available in the current Debian Trixie base sources.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        default-jre-headless \
        qpdf \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-spa \
        ghostscript \
        wget \
        unzip \
        git \
        curl \
        ca-certificates \
        python3 \
        python3-pip \
        python3-dev \
        gcc \
        g++ \
        bash \
        fontconfig \
        fonts-liberation \
        fonts-croscore \
        fonts-crosextra-carlito \
        fonts-crosextra-caladea \
        fonts-urw-base35 \
        fonts-texgyre \
        fonts-noto-core \
        fonts-noto-mono \
        fonts-noto-cjk \
        fonts-noto-color-emoji \
        fonts-noto \
        fonts-open-sans \
        fonts-roboto \
        fonts-dejavu-core \
        fonts-freefont-ttf \
        fonts-lato \
        fonts-hack \
        fonts-inconsolata \
        fonts-anonymous-pro \
        fonts-firacode \
        fonts-jetbrains-mono \
        fonts-inter \
        fonts-atkinson-hyperlegible-ttf \
        fonts-paratype \
        fonts-stix \
        fonts-sil-charis \
        fonts-sil-andika \
        fonts-sil-scheherazade \
        fonts-sil-gentiumplus \
        fonts-linuxlibertine \
        fonts-cantarell \
        fonts-droid-fallback \
        fonts-noto-extra \
        fonts-symbola \
        fonts-opensymbol \
        fonts-hosny-amiri \
        fonts-wqy-zenhei \
        fonts-ipafont \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

# Install veraPDF Arlington.
# The response XML is generated inline from the legacy file so no extra repo
# resource is required.
RUN bash -euxo pipefail <<'SCRIPT'
cat > /tmp/verapdf-install-response.xml <<'EOF'
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<AutomatedInstallation langpack="eng">
  <com.izforge.izpack.panels.htmlhello.HTMLHelloPanel id="welcome"/>
  <com.izforge.izpack.panels.target.TargetPanel id="install_dir">
    <installpath>/opt/verapdf</installpath>
  </com.izforge.izpack.panels.target.TargetPanel>
  <com.izforge.izpack.panels.packs.PacksPanel id="sdk_pack_select">
    <pack index="0" name="veraPDF GUI" selected="false"/>
    <pack index="1" name="veraPDF CLI" selected="true"/>
    <pack index="2" name="veraPDF Documentation" selected="false"/>
    <pack index="3" name="veraPDF Sample Plugins" selected="false"/>
  </com.izforge.izpack.panels.packs.PacksPanel>
  <com.izforge.izpack.panels.install.InstallPanel id="install"/>
  <com.izforge.izpack.panels.finish.FinishPanel id="finish"/>
</AutomatedInstallation>
EOF

mkdir -p /tmp/verapdf-arlington
curl -fL \
  "https://software.verapdf.org/releases/arlington/1.30/verapdf-arlington-${VERAPDF_VERSION}-installer.zip" \
  -o /tmp/verapdf-arlington-installer.zip
unzip -q /tmp/verapdf-arlington-installer.zip -d /tmp/verapdf-arlington
installer="$(find /tmp/verapdf-arlington -type f -name verapdf-install | head -n 1)"
test -n "$installer"
chmod +x "$installer"
"$installer" /tmp/verapdf-install-response.xml
test -x "$VERAPDF_ARLINGTON_BIN"
"$VERAPDF_ARLINGTON_BIN" --version || true

rm -rf \
  /tmp/verapdf-install-response.xml \
  /tmp/verapdf-arlington \
  /tmp/verapdf-arlington-installer.zip
SCRIPT

# Install veraPDF Greenfield.
# The response XML is generated inline from the legacy file so no extra repo
# resource is required.
RUN bash -euxo pipefail <<'SCRIPT'
cat > /tmp/verapdf-greenfield-install-response.xml <<'EOF'
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<AutomatedInstallation langpack="eng">
  <com.izforge.izpack.panels.htmlhello.HTMLHelloPanel id="welcome"/>
  <com.izforge.izpack.panels.target.TargetPanel id="install_dir">
    <installpath>/opt/verapdf-greenfield</installpath>
  </com.izforge.izpack.panels.target.TargetPanel>
  <com.izforge.izpack.panels.packs.PacksPanel id="sdk_pack_select">
    <pack index="0" name="veraPDF GUI" selected="false"/>
    <pack index="1" name="veraPDF Mac and *nix Scripts" selected="true"/>
    <pack index="2" name="veraPDF Validation model" selected="true"/>
    <pack index="3" name="veraPDF Documentation" selected="false"/>
    <pack index="4" name="veraPDF Sample Plugins" selected="false"/>
  </com.izforge.izpack.panels.packs.PacksPanel>
  <com.izforge.izpack.panels.install.InstallPanel id="install"/>
  <com.izforge.izpack.panels.finish.FinishPanel id="finish"/>
</AutomatedInstallation>
EOF

mkdir -p /tmp/verapdf-greenfield
curl -fL \
  "https://software.verapdf.org/releases/1.30/verapdf-greenfield-${VERAPDF_VERSION}-installer.zip" \
  -o /tmp/verapdf-greenfield-installer.zip
unzip -q /tmp/verapdf-greenfield-installer.zip -d /tmp/verapdf-greenfield
installer="$(find /tmp/verapdf-greenfield -type f -name verapdf-install | head -n 1)"
test -n "$installer"
chmod +x "$installer"
"$installer" /tmp/verapdf-greenfield-install-response.xml
test -x "$VERAPDF_GREENFIELD_BIN"
"$VERAPDF_GREENFIELD_BIN" --version || true

rm -rf \
  /tmp/verapdf-greenfield-install-response.xml \
  /tmp/verapdf-greenfield \
  /tmp/verapdf-greenfield-installer.zip
SCRIPT

# Install the current repo's Python remediation requirements.
# The requirements file remains the source of truth for system Python packages.
#
# The Hermes base image runs its gateway/tooling under /opt/hermes/.venv/bin/python3,
# but that venv does not include pip. Use system pip to install only the verified
# missing runtime dependency, PyMuPDF, into the Hermes venv site-packages so
# Hermes-invoked remediation tools can import fitz without disturbing Hermes'
# own pinned dependencies.
WORKDIR /app
COPY app/requirements.txt /tmp/requirements.txt
RUN /usr/bin/python3 -m pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && hermes_site="$('/opt/hermes/.venv/bin/python3' -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')" \
    && /usr/bin/python3 -m pip install --no-cache-dir --break-system-packages --target "$hermes_site" pymupdf==1.27.1 \
    && rm -f /tmp/requirements.txt

# Keep validation profiles in the image, then seed them into the bind-mounted
# workspace at container startup. Files baked directly into /app/workspace would
# be hidden by the compose bind mount.
RUN rm -rf "$VERAPDF_PROFILE_SOURCE" \
    && git clone --depth 1 \
        --branch integration \
        https://github.com/veraPDF/veraPDF-validation-profiles.git \
        "$VERAPDF_PROFILE_SOURCE" \
    && test -d "$VERAPDF_PROFILE_SOURCE/PDF_UA"

# NOTE: an earlier empty cont-init seed script for veraPDF profiles was
# removed (P10). The orchestrator reads profiles directly from the in-image
# VERAPDF_PROFILE_SOURCE path; no workspace seeding occurs at container init.

WORKDIR /app
