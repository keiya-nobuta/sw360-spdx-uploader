# sw360-spdx-uploader

## Installing

```
python -m venv venv
source venv/bin/activate
pip install git+https://github.com/keiya-nobuta/sw360-spdx-uploader
```

## Usage

To use this, you need to set the sw360 REST-API server URL and API token via SW360_URL (or --url) and SW360_SECRET (or --secret)

```
Usage: sw360-cli [OPTIONS] COMMAND [ARGS]...

Options:
  --url TEXT     Set SW360 REST-API endpoint instead of SW360_URL
  --secret TEXT  Set REST-API key instead of SW360_SECRET
  --help         Show this message and exit.

Commands:
  create-component
  create-license
  create-project
  create-release
  get-component
  get-license
  get-project
  get-release
  update-release
  upload-attachment
  upload-spdx
```

upload spdx example:

```
SW360_URL='your-server-url' SW360_SECRET='your-api-token' sw360-cli upload-spdx --name 'test project' --version '0.0.1-test' sbom.spdx
```


