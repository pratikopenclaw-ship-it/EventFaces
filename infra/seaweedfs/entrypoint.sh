#!/bin/sh
# Local-dev S3 (SeaweedFS). Writes the S3 identity from env vars, then starts
# master + volume + filer + S3 gateway in one process.
set -e
cat > /tmp/s3.json <<JSON
{"identities":[{"name":"eventfaces","credentials":[{"accessKey":"${S3_ACCESS_KEY}","secretKey":"${S3_SECRET_KEY}"}],"actions":["Admin","Read","List","Tagging","Write"]}]}
JSON
# Fixed volume count (not derived from free disk space, which on CI runners left too few
# volumes for a new bucket: PutObject "InternalError"); small volumes, nothing preallocated.
exec weed server -dir=/data -s3 -s3.port=8333 -s3.config=/tmp/s3.json -volume.max=50 -master.volumeSizeLimitMB=256
