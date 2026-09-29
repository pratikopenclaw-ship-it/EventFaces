#!/bin/sh
# Local-dev S3 (SeaweedFS). Writes the S3 identity from env vars, then starts
# master + volume + filer + S3 gateway in one process.
set -e
cat > /tmp/s3.json <<JSON
{"identities":[{"name":"eventfaces","credentials":[{"accessKey":"${S3_ACCESS_KEY}","secretKey":"${S3_SECRET_KEY}"}],"actions":["Admin","Read","List","Tagging","Write"]}]}
JSON
exec weed server -dir=/data -s3 -s3.port=8333 -s3.config=/tmp/s3.json -volume.max=0 -master.volumeSizeLimitMB=1024
