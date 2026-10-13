# DSG Cinema — GnuTLS-free native dependency record
**Date:** 2026-10-12 · **Target:** AWS-only self-hosted Cinema / DSG OS shared Playwright runtime

## Origin and scope
The previously pushed candidate image `sha256:72234d126d22249476517d6a6f2407cfd89a018c5df1a32953e425c9c1603e52` was correctly stopped by AWS ECR (`CVE-2026-95210`, `CVE-2026-88647`, GnuTLS, 2 CRITICAL). The running image remained unchanged. This document records the **experimental, code-reviewed replacement** in PR #267 until a new immutable release passes independent ECR scan.

The previous distro package closure pulled GnuTLS through both:
- `git -> libcurl3t64-gnutls -> GnuTLS`
- `Chromium -> libcups2t64 -> GnuTLS`

Switching the distro `libcurl4t64` package to OpenSSL would **not** eliminate GnuTLS: Debian `librtmp1` depends on it. Updating `apt` or renaming a provider would not remedy either CVE.

## Native source and license obligations

| Native library | Source and exact version | Build contract | Bundled notices | Functional limitation |
| --- | --- | --- | --- | --- |
| Git | Debian signed `git` source `1:2.47.3-0+deb13u1` via dated Debian snapshot APT `deb-src` | `NO_CURL=YesPlease` to support **local** `init/commit/clone/checkout` only | `/opt/dsg-local-git/GIT-COPYING` (GPL) | Git HTTP(S) remote transport deliberately omitted; remote provider/network operations must use separately governed adapters |
| CUPS libcups.so.2 | Debian signed `cups` source `2.4.10-3+deb13u2` via dated Debian snapshot APT `deb-src` | `./configure --with-tls=openssl`, build real CUPS client shared library and link against OpenSSL | `/opt/dsg-openssl-cups/CUPS-LICENSE`, `/opt/dsg-openssl-cups/CUPS-NOTICE` | CUPS daemon not installed; Chromium client library remains dynamically linked |

Debian source package manifests/changelogs and archive signatures are inherited from signed APT metadata. Changes to source-build configurations are recorded in `Dockerfile.cinema`. The custom-compiled components are now built as **explicit local `.deb` packages** with package names `git` and `libcups2t64`, Debian source-version identities, DSG `+dsg1` build suffixes, and standard `dpkg` inventory records. The packages retain native Git/CUPS license notices. This gives the ECR Debian OS-package scanner component names/versions rather than silently omitting all source-built native code. Because these binaries are custom builds and external package scanners do not necessarily understand every source patch or every native dependency, **ECR Critical=0 is not a guarantee that upstream Git/CUPS have zero vulnerabilities**. Keep an explicit source SBOM and separate advisories/security review. The exact code and compile flags are available in `Dockerfile.cinema`.

## Required release gate
- [ ] Current-commit CI compiles the exact source and builds the immutable Cinema image.
- [ ] Chromium Playwright starts and reads a test page without injecting a dummy CUPS library.
- [ ] Runtime `dpkg-query` lists custom `git` and `libcups2t64` with explicit source versions; `ldconfig -p` and Chromium `ldd` prove no GnuTLS dependency; no absent ELF dependencies. 
- [ ] Custom CUPS ELF has `GNU_RELRO` and `BIND_NOW` linker hardening; source archives are pinned to the dated signed Debian snapshot.
- [ ] **Local** Git init/commit/clone succeeds (not a network-enabled Git claim).
- [ ] No retired external browser sidecar is bundled.
- [ ] Current-commit ECR scan `COMPLETE` with `CRITICAL=0`, no suppression or override.
- [ ] Only then operator-approved deploy to **existing** EC2, new running digest readback and user-bound low-risk Cinema status.
- [ ] Separate signed Connect/Execute approval/E2E evidence, Viewer/Memory continuity, and DSG OS Browser Twin/Recovery/Core Spin verification remain independent.

**No production activation or claim of Cinema high-risk E2E completion follows from a Docker image build or an ECR scan.**

References: [Debian GnuTLS tracker](https://security-tracker.debian.org/tracker/source-package/gnutls28), [Debian CUPS package](https://security-tracker.debian.org/tracker/source-package/cups), [PR #267](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/pull/267), [Blocker #266](https://github.com/tdealer01-crypto/DSG-Cinema-Proof-Agent/issues/266), [Runtime Canonical Issue #656](https://github.com/tdealer01-crypto/DSG-Private-Production-Runtime/issues/656).
