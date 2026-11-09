# Python wheel license inventory

Target: Windows x86-64, CPython 3.12.14. License values come from each downloaded wheel's METADATA; listed license files are included in that wheel.
This inventory records Python distributions and bundled license files. Native runtime versions are reported separately by `doctor`; review any new wheel or bundled native component before adopting a later lock.

| Distribution | Version | Wheel license metadata | Included license files |
|---|---:|---|---|
| certifi | 2026.10.23 | MPL-2.0 | LICENSE |
| charset-normalizer | 3.5.2 | MIT | LICENSE |
| colorama | 0.4.6 | UNSPECIFIED | LICENSE.txt |
| geopandas | 1.2.0 | BSD-3-Clause | LICENSE.txt |
| idna | 3.20 | BSD-3-Clause | LICENSE.md |
| iniconfig | 2.3.1 | MIT | LICENSE |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | LICENSE.txt, numpy/fft/pocketfft/LICENSE.md, numpy/linalg/lapack_lite/LICENSE.txt, numpy/ma/LICENSE, numpy/random/LICENSE.md (+12 more) |
| osmium | 4.3.2 | BSD-2-Clause | LICENSE.TXT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | LICENSE, LICENSE.APACHE, LICENSE.BSD |
| pandas | 3.1.0 | BSD-3-Clause | LICENSE, LICENSES/BOTTLENECK_LICENCE, LICENSES/DATEUTIL_LICENSE, LICENSES/HAVEN_LICENSE, LICENSES/HAVEN_MIT (+14 more) |
| pip | 26.2.2 | MIT | AUTHORS.txt, LICENSE.txt, src/pip/_vendor/cachecontrol/LICENSE.txt, src/pip/_vendor/certifi/LICENSE, src/pip/_vendor/distlib/LICENSE.txt (+17 more) |
| pluggy | 1.7.0 | MIT | LICENSE |
| psutil | 7.2.2 | BSD-3-Clause | No separate license file |
| Pygments | 2.21.0 | BSD-2-Clause | AUTHORS, LICENSE |
| pyogrio | 0.13.0 | MIT License | LICENSE |
| pyproj | 3.8.0 | MIT | LICENSE, LICENSE_proj |
| pytest | 9.2.0 | MIT | LICENSE |
| python-dateutil | 4.0.0 | BSD-3-Clause | AUTHORS.md, LICENSE |
| requests | 2.34.2 | Apache-2.0 | LICENSE, NOTICE |
| setuptools | 80.9.0 | MIT | LICENSE, LICENSE |
| shapely | 2.2.0 | BSD-3-Clause | LICENSE.txt, LICENSE_GEOS, LICENSE_win32 |
| tzdata | 2026.6 | Apache-2.0 | LICENSE, licenses/LICENSE_APACHE |
| urllib3 | 2.8.0 | MIT | LICENSE.txt |

## Bundled native binary files

These filenames come from the exact wheel archives used to build the lock. Their runtime versions and known upstream license terms are summarized in `environment-win-py312.md`.

| Distribution | Native binary files |
|---|---|
| charset-normalizer 3.5.2 | `charset_normalizer/cd.cp312-win_amd64.pyd, charset_normalizer/md.cp312-win_amd64.pyd` |
| numpy 2.5.4 | `numpy/fft/_pocketfft_umath.cp312-win_amd64.pyd, numpy/linalg/lapack_lite.cp312-win_amd64.pyd, numpy/linalg/_umath_linalg.cp312-win_amd64.pyd, numpy/random/bit_generator.cp312-win_amd64.pyd, numpy/random/mtrand.cp312-win_amd64.pyd, numpy/random/_bounded_integers.cp312-win_amd64.pyd, numpy/random/_common.cp312-win_amd64.pyd, numpy/random/_generator.cp312-win_amd64.pyd, numpy/random/_mt19937.cp312-win_amd64.pyd, numpy/random/_pcg64.cp312-win_amd64.pyd, numpy/random/_philox.cp312-win_amd64.pyd, numpy/random/_sfc64.cp312-win_amd64.pyd, numpy/_core/_multiarray_tests.cp312-win_amd64.pyd, numpy/_core/_multiarray_umath.cp312-win_amd64.pyd, numpy/_core/_operand_flag_tests.cp312-win_amd64.pyd, numpy/_core/_rational_tests.cp312-win_amd64.pyd, numpy/_core/_simd.cp312-win_amd64.pyd, numpy/_core/_struct_ufunc_tests.cp312-win_amd64.pyd, numpy/_core/_umath_tests.cp312-win_amd64.pyd, numpy.libs/libscipy_openblas64_-ed4f167a5330424524f45258e7ca2c8d.dll, numpy.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll` |
| osmium 4.3.2 | `osmium/area.cp312-win_amd64.pyd, osmium/filter.cp312-win_amd64.pyd, osmium/geom.cp312-win_amd64.pyd, osmium/index.cp312-win_amd64.pyd, osmium/io.cp312-win_amd64.pyd, osmium/_osmium.cp312-win_amd64.pyd, osmium/osm/_osm.cp312-win_amd64.pyd, osmium/replication/_replication.cp312-win_amd64.pyd, osmium.libs/bz2-134255cadab81664bb5cb41f5ac94a8d.dll, osmium.libs/libexpat-89c59b084838910c7c04568f9625f12c.dll, osmium.libs/lz4-a40b1dffda3d2d34329b471fe430c488.dll, osmium.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll, osmium.libs/z-071dc640d525369a5843a35e81c8f9a4.dll` |
| pandas 3.1.0 | `pandas/_libs/algos.cp312-win_amd64.pyd, pandas/_libs/arrays.cp312-win_amd64.pyd, pandas/_libs/byteswap.cp312-win_amd64.pyd, pandas/_libs/groupby.cp312-win_amd64.pyd, pandas/_libs/hashing.cp312-win_amd64.pyd, pandas/_libs/hashtable.cp312-win_amd64.pyd, pandas/_libs/index.cp312-win_amd64.pyd, pandas/_libs/indexing.cp312-win_amd64.pyd, pandas/_libs/internals.cp312-win_amd64.pyd, pandas/_libs/interval.cp312-win_amd64.pyd, pandas/_libs/join.cp312-win_amd64.pyd, pandas/_libs/lib.cp312-win_amd64.pyd, pandas/_libs/missing.cp312-win_amd64.pyd, pandas/_libs/ops.cp312-win_amd64.pyd, pandas/_libs/ops_dispatch.cp312-win_amd64.pyd, pandas/_libs/pandas_datetime.cp312-win_amd64.pyd, pandas/_libs/pandas_parser.cp312-win_amd64.pyd, pandas/_libs/parsers.cp312-win_amd64.pyd, pandas/_libs/properties.cp312-win_amd64.pyd, pandas/_libs/reshape.cp312-win_amd64.pyd, pandas/_libs/sas.cp312-win_amd64.pyd, pandas/_libs/sparse.cp312-win_amd64.pyd, pandas/_libs/testing.cp312-win_amd64.pyd, pandas/_libs/tslib.cp312-win_amd64.pyd, pandas/_libs/writers.cp312-win_amd64.pyd, pandas/_libs/_cyutility.cp312-win_amd64.pyd, pandas/_libs/_ujson.cp312-win_amd64.pyd, pandas/_libs/tslibs/base.cp312-win_amd64.pyd, pandas/_libs/tslibs/ccalendar.cp312-win_amd64.pyd, pandas/_libs/tslibs/conversion.cp312-win_amd64.pyd, pandas/_libs/tslibs/dtypes.cp312-win_amd64.pyd, pandas/_libs/tslibs/fields.cp312-win_amd64.pyd, pandas/_libs/tslibs/nattype.cp312-win_amd64.pyd, pandas/_libs/tslibs/np_datetime.cp312-win_amd64.pyd, pandas/_libs/tslibs/offsets.cp312-win_amd64.pyd, pandas/_libs/tslibs/parsing.cp312-win_amd64.pyd, pandas/_libs/tslibs/period.cp312-win_amd64.pyd, pandas/_libs/tslibs/strptime.cp312-win_amd64.pyd, pandas/_libs/tslibs/timedeltas.cp312-win_amd64.pyd, pandas/_libs/tslibs/timestamps.cp312-win_amd64.pyd, pandas/_libs/tslibs/timezones.cp312-win_amd64.pyd, pandas/_libs/tslibs/tzconversion.cp312-win_amd64.pyd, pandas/_libs/tslibs/vectorized.cp312-win_amd64.pyd, pandas/_libs/window/aggregations.cp312-win_amd64.pyd, pandas/_libs/window/indexers.cp312-win_amd64.pyd, pandas.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll` |
| psutil 7.2.2 | `psutil/_psutil_windows.pyd` |
| pyogrio 0.13.0 | `pyogrio/_err.pyd, pyogrio/_geometry.pyd, pyogrio/_io.pyd, pyogrio/_ogr.pyd, pyogrio/_vsi.pyd, pyogrio.libs/gdal-9fa6a5301668010b1474299a888c26da.dll, pyogrio.libs/geos-bda2e4a35fc87c3cb436d3add2953ffb.dll, pyogrio.libs/geos_c-05968ceb6a9aade9961ca529050ada59.dll, pyogrio.libs/geotiff-0f08c58b982b142224f2707f8e49d843.dll, pyogrio.libs/iconv-2-ec6407dc8b081563527a51db783233cc.dll, pyogrio.libs/jpeg62-c79c71e9654a1a62b02167aa47efcfc1.dll, pyogrio.libs/json-c-23e40dddc89c5be9375747232d8f35fb.dll, pyogrio.libs/Lerc-c10f5743f8921c17b85576614838c379.dll, pyogrio.libs/libcrypto-3-x64-7b8fb6ee347e3e4ee5e92cf5f7691e7d.dll, pyogrio.libs/libcurl-c3697df4ff70334a5320d2218a143c97.dll, pyogrio.libs/libexpat-6d13c47b98550978af0962920611301e.dll, pyogrio.libs/liblzma-72d8c4b09cb84a63a20b48cc6de0e301.dll, pyogrio.libs/libpng16-51f4f376c28be4f3fee815c154d2d249.dll, pyogrio.libs/libssl-3-x64-ce0f27858f99fd8e7c41e6e39bd2f7b6.dll, pyogrio.libs/libxml2-3983679bc2aba685351f42b9f58ab67c.dll, pyogrio.libs/minizip-09a8b95a475f7786cff4765c06464595.dll, pyogrio.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll, pyogrio.libs/proj_9-6329b13d4c90abfce1c9dc07fa75284e.dll, pyogrio.libs/qhull_r-a82503bf44e8253baabe69c074cb5ce3.dll, pyogrio.libs/spatialite-d8c2d6ee9614ee788aabd66cd9557079.dll, pyogrio.libs/sqlite3-a62ef28d840863c87680b78bee9c5ae7.dll, pyogrio.libs/tiff-bb811e0d8708ee7a0f2bdfdea67ef0bc.dll, pyogrio.libs/z-be29236fe53451bd4768a6900713c673.dll` |
| pyproj 3.8.0 | `pyproj/database.cp312-win_amd64.pyd, pyproj/list.cp312-win_amd64.pyd, pyproj/_compat.cp312-win_amd64.pyd, pyproj/_context.cp312-win_amd64.pyd, pyproj/_crs.cp312-win_amd64.pyd, pyproj/_geod.cp312-win_amd64.pyd, pyproj/_network.cp312-win_amd64.pyd, pyproj/_sync.cp312-win_amd64.pyd, pyproj/_transformer.cp312-win_amd64.pyd, pyproj/_version.cp312-win_amd64.pyd, pyproj.libs/jpeg62-971fedc88cb0e86c3ad978ae1b7646db.dll, pyproj.libs/libcurl-f49442d4be7d953952a0509cdd4501fa.dll, pyproj.libs/liblzma-3c4c8780fcad6ce56344d2b5594bda5b.dll, pyproj.libs/msvcp140-7c26614e1d733892c2deac7e245ce115.dll, pyproj.libs/proj_9-7e5618bddacc5af688a84f477cf114c3.dll, pyproj.libs/sqlite3-9415ebc42378ab15b741623972c45846.dll, pyproj.libs/tiff-69dcdf91c822b00d23e8dbf49655fe78.dll, pyproj.libs/zlib1-985e9fefa27bf900be8e4df7dcc97287.dll` |
| shapely 2.2.0 | `shapely/lib.cp312-win_amd64.pyd, shapely/_geometry_helpers.cp312-win_amd64.pyd, shapely/_geos.cp312-win_amd64.pyd, shapely.libs/geos-bf067cd6ff74ee0ad5f3ff52c7ef08c9.dll, shapely.libs/geos_c-6dd9fd915eef8a7928285416bef1e666.dll, shapely.libs/msvcp140-0fa7eb792d3fbcf2233e4ea47e9144b9.dll` |

## JSON Schema validator dependency set (Task 5.2)

These exact Windows x86-64 CPython 3.12.14 wheels are in `requirements-package-win-py312.lock.txt`; their SHA-256 hashes were calculated from downloaded wheel bytes. License identifiers/files were read from wheel METADATA/archive contents.

| Distribution | Version | Wheel license metadata | Included license files |
|---|---:|---|---|
| attrs | 26.1.0 | MIT | LICENSE |
| jsonschema | 4.25.1 | MIT | COPYING |
| jsonschema-specifications | 2025.9.1 | MIT | COPYING |
| referencing | 0.37.0 | MIT | COPYING |
| rpds-py | 2026.9.1 | MIT | LICENSE |
| typing_extensions | 4.16.0 | PSF-2.0 | LICENSE |
