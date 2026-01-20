import sw360
import sys
import click
import json
import datetime
import urllib

_context = {}

def _init_api_client(url, secret):
    if not url:
        raise ValueError('--url or SW360_URL envvar needed.')
    if not secret:
        raise ValueError('--secret or SW360_SECRET envvar needed.')

    client = sw360.SW360(url = url, token = secret)
    client.force_no_session = True

    _context['client'] = client

    return client

def _get_api_client():
    return _context['client']

def __releases(component):
    return (component.get('_embedded') or {}).get('sw360:releases') or []

def _create_project(sw360_client, name, version='', description='', type='PRODUCT', visibility='PRIVATE'):
    '''
    Create Project if not exists
    '''

    if not all((name,)):
        raise ValueError(f'name({name}) is invalid')

    project = None

    resp = sw360_client.get_projects_by_name(name)
    if resp:
        project = next((p for p in resp if p['version'] == version), None)

    if not project:
        project = sw360_client.create_new_project(
            name = name,
            project_type = type,
            visibility = visibility,
            description = description,
            version = version,
        )

        if not project:
            print(f'ERROR: Cannot create Project ({name})', file=sys.stderr)
            return None

    return project

def _get_component_by_name(sw360_client, name):
    resp = sw360_client.get_component_by_name(name)
    return next(iter((resp.get('_embedded') or {}).get('sw360:components') or []), None)

def _create_component(sw360_client, name, description='', type='INTERNAL', homepage=''):
    '''
    Create Component if not exists
    '''

    if not all((name,)):
        raise ValueError(f'name({name}) is invalid')

    component = _get_component_by_name(sw360_client, name)
    if not component:
        component = sw360_client.create_new_component(name, description, type, homepage)
        if not component:
            print(f'ERROR: Cannot create Component ({name})', file=sys.stderr)

    return component

def _create_license(sw360_client, short_name, full_name=None, extracted_text=None, checked: bool = False, *args, **kwds):
    '''
    Create new license
    '''
    if not all((short_name,)):
        raise ValueError(f'short_name({short_name}) is invalid')

    lic = _get_license(sw360_client, short_name)
    if lic:
        return lic

    if not full_name:
        full_name = short_name

    resp = sw360_client.create_new_license(
        shortName = short_name,
        fullName = full_name,
        text = extracted_text,
        checked = checked,
    )

    return resp

def _get_license(sw360_client, short_name):
    '''
    Get registered license
    '''
    try:
        return sw360_client.get_license(short_name)
    except:
        return None

def __dict_copy_fields(d, *fields):
    return {f: d.get(f) for f in fields if f in d}

def _bulk_add_licenses(sw360_client, licenses):
    license_list = []

    for license in licenses:
        license_name = license['short_name']
        exist_license = _get_license(sw360_client, license_name)
        if not exist_license:
            try:
                exist_licesne = _create_license(sw360_client, **license)
            except Exception as e:
                print(f'create license ({license}) failed with {e}')
                continue

        if exist_license:
            license_list.append(exist_license['shortName'])
        else:
            print(f'license ({license}) not registered on SW360', file=sys.stderr)

    return license_list

def _update_release(sw360_client, release_id, version='',
                    cpe_id='', download_url='', licenses=[], other_licenses=[],
                    operating_systems=[], software_platforms=[]):

    release = sw360_client.get_release(release_id)
    if not release:
        raise KeyError(f'release ({release_id}) not found')

    update_release = __dict_copy_fields(release,
        'id',
        'version',
        'operationgSystems',
        'softwarePlatforms',
        'cpeId',
        'sourceCodeDownloadURL',
        '_embedded',
    )
    if version:
        update_release['version'] = version
    if operating_systems:
        update_release['operatingSystems'] = list(operating_systems)
    if software_platforms:
        update_release['softwarePlatforms'] = list(software_platforms)
    if cpe_id:
        update_release['cpeId'] = cpe_id
    if download_url:
        update_release['sourceCodeDownloadURL'] = download_url

    main_license_list = _bulk_add_licenses(sw360_client, licenses)
    other_license_list = _bulk_add_licenses(sw360_client, other_licenses)

    if main_license_list:
        update_release['mainLicenseIds'] = main_license_list

    if other_license_list:
        update_release['otherLicenseIds'] = other_license_list

    resp = {}
    if release != update_release:
        update_release['releaseDate'] = datetime.datetime.today().strftime('%Y-%m-%d')
        resp = sw360_client.update_release(
                release = update_release,
                release_id = release_id
        )

    return resp

def _create_release(sw360_client, component_id, name, version,
                    cpe_id='', download_url='', licenses=[], other_licenses=[], release=None,
                    operating_systems=[], software_platforms=[]):
    if not all((any((component_id, name)), version)):
        raise ValueError(f'component_id({component_id}) or name({name}) or version({version}) are invalid')

    if component_id:
        component = sw360_client.get_component(component_id)
        if not component:
            raise KeyError(f'Component ({component_id}) not found')

        name = component.get('name')
    elif name:
        component = _get_component_by_name(sw360_client, name)
        if not component:
            raise KeyError(f'Component ({component_name}) not found')

        component_id = component.get('id')
    else:
        raise ValueError(f'Component id or name is required')

    if not release:
        releases = sw360_client.get_releases_by_name(component.get('name'))
        release = next((r for r in releases if r.get('version') == version), None)

        if not release:
            release = sw360_client.create_new_release(name, version, component_id)

    if not release:
        raise ValueError('Release ({name} {version}) cannot create')

    release_id = release.get('id')
    resp = _update_release(sw360_client,
        release_id = release_id,
        version = version,
        cpe_id = cpe_id, 
        download_url = download_url,
        licenses = licenses,
        other_licenses = other_licenses,
        operating_systems = operating_systems,
        software_platforms = software_platforms,
    )

    return resp

def _upload_attachment(sw360_client, release_id, attach_path, attach_type):
    attach_name = os.path.basename(attach_path)
    resp = sw360_client.get_attachment_infos_for_release(release_id)
    if resp:
        for attach in resp:
            if attach['filename'] == attach_name:
                return None

    resp = sw360_client.upload_release_attachment(release_id, attach_path,
                                                  upload_type=attach_type)
    return resp

def __spdx_package_cpe(package):
    for ref in package.external_references:
        if 'cpe23type' in ref.reference_type.lower():
            return ref.locator

    return ''

def _spdx_license(spdxdata, license_ref):
    from dataclasses import asdict

    license_info = next((lic for lic in spdxdata.extracted_licensing_info if lic.license_id == license_ref), None)
    return license_info

def _spdx_licenses(spdxdata, license_exp):
    from license_expression import get_spdx_licensing

    if not license_exp:
        return []

    licensing = get_spdx_licensing()
    parsed = licensing.parse(license_exp)

    ret = []
    for license_ref in parsed.literals:
        license_info = _spdx_license(spdxdata, license_ref)
        if license_info:
            ret.append({
                'short_name': license_info.license_name,
                'full_name': license_info.license_name,
                'text': license_info.extracted_text,
            })
        else:
            ret.append({
                'short_name': license_ref,
                'full_name': license_ref,
                'extracted_text': None,
            })

    return ret

def _import_spdx(sw360_client, project_name, project_version, spdx_path, *args, **kwds):
    from spdx_tools.spdx.parser.parse_anything import parse_file

    spdx = parse_file(spdx_path)

    release_ids = set()

    for package in spdx.packages:
        try:
            component = _create_component(sw360_client,
                name = str(package.name),
                description = '\n\n'.join(
                    str(text) for text in (package.summary, package.description, package.comment) if text
                ),
                homepage = str(package.homepage),
            )
        except Exception as e:
            print(f'Error: create component ({package.name}) failed with "{e}"', file=sys.stderr)
            continue

        if not component:
            print(f'Error: create component ({package.name})', file=sys.stderr)
            continue

        component_id = component['id']
        release = next(
            (release for release in __releases(component) if release['version'] == package.version),
            None
        )

        license_exp = str(package.license_concluded) if str(package.license_concluded) != 'NOASSERTION' else None
        licenses = _spdx_licenses(spdx, license_exp)
        other_license_exp = str(package.license_declared) if str(package.license_declared) != 'NOASSERTION' else None
        other_licenses = _spdx_licenses(spdx, other_license_exp)

        try:
            updated_release = _create_release(sw360_client,
                component_id,
                str(package.name),
                str(package.version),
                cpe_id = __spdx_package_cpe(package),
                download_url = str(package.download_location),
                licenses = licenses,
                other_licenses = other_licenses,
                release = release,
            )
        except Exception as e:
            print(f'Error create release ({package.name} {package.version}) failed with "{e}"')
            continue

        if not updated_release:
            print('Error: add release ({package.name} {package.version}) failed', file=sys.stderr)
            continue

        release_id = updated_release['id']
        print(f'create release {release_id}: {package.name} {package.version}', file=sys.stderr)

        release_ids.add(updated_release['id'])

    try:
        project = _create_project(sw360_client, project_name, project_version)
    except Exception as e:
        print(f'Error: create project ({project_name}) failed with "{e}"', file=sys.stderr)

    if not project:
        sys.exit('Error: create project ({project_name} {project_version})')

    resp = sw360_client.update_project_releases(
        releases = list(release_ids),
        project_id = project['id'],
        add = False, # add given releases if set to True, replace otherwise
    )
    project_id = project['id']
    print(f'create project {project_id}: {project_name} {project_version}', file=sys.stderr)

    return resp


@click.group()
@click.option('--url', envvar='SW360_URL', help='Set SW360 REST-API endpoint instead of SW360_URL')
@click.option('--secret', envvar='SW360_SECRET', help='Set REST-API key instead of SW360_SECRET')
def cli(url, secret):
    _init_api_client(url, secret)

@cli.command()
@click.option('-n', '--name', required=True, help='Project Name')
@click.option('-v', '--version', default='', help='Project Version')
@click.option('--description', default='', help='Project description')
@click.option('-t', '--type', default='PRODUCT', help='Project Type, one of "CUSTOMER", "INTERNAL", "PRODUCT", "SERVICE", "INNER_SOURCE" (default: PRODUCT)')
@click.option('--visibility', default='PRIVATE', help='Project visibility, one of "PRIVATE", "ME_AND_MODERATORS", "BUISNESSUNIT_AND_MODERATORS" (no typo), "EVERYONE" (default: PRIVATE)')
def create_project(name, version, description, type, visibility):
    sw360_client = _get_api_client()

    project = _create_project(sw360_client, name, version, description, type, visibility) or {}
    print(json.dumps(project, indent=2))

@cli.command()
@click.option('--project-id', multiple=True, help='Project IDs')
@click.option('-n', '--name', multiple=True, help='Project Names')
def get_project(project_id, name):
    sw360_client = _get_api_client()

    resp = [
        sw360_client.get_project(id)
        for id in project_id
    ]

    for n in name:
        r = sw360_client.get_projects_by_name(n)
        resp += r

    print(json.dumps(resp, indent=2))

@cli.command()
@click.option('-n', '--name', required=True, help='Component Name')
@click.option('--description', default='', help='Component description')
@click.option('-t', '--type', default='INTERNAL', help='Component Type, one of "INTERNAL", "OSS", "COTS", "FREESOFTWARE", "INNER_SOURCE", "SERVICE", "CODE_SNIPPET" (default: INTERNAL)')
@click.option('--homepage', default='', help='Component Homepage (default: "")')
def create_component(name, description, type, homepage=''):
    sw360_client = _get_api_client()

    component = _create_component(sw360_client, name, description, type, homepage='') or {}
    print(json.dumps(component, indent=2))

@cli.command()
@click.option('--component-id', multiple=True, help='Component IDs')
@click.option('-n', '--name', multiple=True, help='Component Names')
def get_component(component_id, name):
    sw360_client = _get_api_client()

    resp = [
        sw360_client.get_component(id)
        for id in component_id
    ]

    for n in name:
        component = _get_component_by_name(sw360_client, n) or {'name': n, 'error': f'Not found.'}
        resp.append(component)

    print(json.dumps(resp, indent=2))

@cli.command()
@click.option('--component-id', help='Component ID to add the release to. [Either one is required]')
@click.option('-n', '--name', help='Component Name instead of Component ID. [Either one is required]')
@click.option('-v', '--version', required=True, help='Release Version')
@click.option('--cpe', default='', help='Release CPE-ID (e.g. "cpe:23.:a:apache:http_server:*:*:*:*:*:*:*:*')
@click.option('--download-url', default='', help='Release Download URL')
@click.option('--license', multiple=True, help='Release Main License')
@click.option('--os', multiple=True, help='Operating systems, eg --os "Linux"')
def create_release(component_id, name, version, cpe, download_url, license, os):
    sw360_client = _get_api_client()

    licenses = [{'short_name': lic} for lic in license]

    release = _create_release(
        sw360_client, component_id, name, version,
        cpe, download_url, licenses, operating_systems=os,
    ) or {}

    print(json.dumps(release, indent=2))

@cli.command()
@click.option('--release-id', required=True, help='Component ID to add the release to.')
@click.option('-v', '--version', help='Release Version')
@click.option('--cpe', default='', help='Release CPE-ID (e.g. "cpe:23.:a:apache:http_server:*:*:*:*:*:*:*:*')
@click.option('--download-url', default='', help='Release Download URL')
@click.option('--license', multiple=True, help='Main License')
@click.option('--other-license', multiple=True, help='Other License')
@click.option('--os', multiple=True, help='Operating systems, eg --os "Linux"')
def update_release(release_id, version, cpe, download_url, license, other_license, os):
    sw360_client = _get_api_client()

    licenses = [{'short_name': lic} for lic in license]
    other_licenses = [{'short_name': lic} for lic in other_license]

    release = _update_release(
        sw360_client, release_id, version,
        cpe, download_url, licenses, other_licenses, operating_systems=os,
    ) or {}

    print(json.dumps(release, indent=2))

@cli.command()
@click.option('--release-id', multiple=True, help='Release IDs.')
@click.option('-n', '--name', multiple=True, help='Release names.')
def get_release(release_id, name):
    sw360_client = _get_api_client()

    resp = [
        sw360_client.get_release(rid)
        for rid in release_id
    ]

    for n in name:
        r = sw360_client.get_releases_by_name(n)
        resp += r

    print(json.dumps(resp, indent=2))

@cli.command()
@click.option('--release-id', required=True, help='Release ID to add the attachment to.')
@click.option('--type', default='SOURCE', help='Attachment type (default=SOURCE)')
@click.argument('files', nargs=-1, type=click.Path())
def upload_attachment(release_id, type, files):
    sw360_client = _get_api_client()

    resps = [
        _upload_attachment(sw360_client, release_id, path, type)
        for path in files
    ]

    print(json.dumps(resps, indent=2))

@cli.command()
@click.option('-n', '--name', help='Short name')
@click.option('--full-name', help='Full name')
@click.option('--text', help='License text')
@click.option('--checked/--no-checked', default=False, help='Checked flag')
def create_license(name, full_name, text, checked):
    sw360_client = _get_api_client()

    resp = _create_license(sw360_client, name, full_name, text, checked)

    print(json.dumps(resp, indent=2))

@cli.command()
@click.option('-a', '--all', is_flag=True, help='Get all licenses')
@click.argument('short-name', nargs=-1)
def get_license(all, short_name):
    sw360_client = _get_api_client()

    if all:
        resp = sw360_client.get_all_licenses()
    else:
        resp = [sw360_client.get_license(n) for n in short_name]

    print(json.dumps(resp, indent=2))

@cli.command()
@click.option('-n', '--name', required=True, help='Project Name')
@click.option('-v', '--version', required=True, help='Project Version')
@click.argument('spdxfile', nargs=1, type=click.Path())
def upload_spdx(name, version, spdxfile):
    sw360_client = _get_api_client()

    resp = _import_spdx(sw360_client,
        project_name = name,
        project_version = version,
        spdx_path = spdxfile,
    ) or {}

    print(json.dumps(resp, indent=2))

if __name__ == '__main__':
    cli()
