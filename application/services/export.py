from logging import getLogger
import subprocess
import re
from nameko.rpc import rpc
from boto.s3.key import Key
from boto.s3.connection import Location
from application.dependencies.s3 import S3


_log = getLogger(__name__)


class ExportServiceError(Exception):
    pass


class ExportService(object):
    name = 'exporter'

    s3 = S3()

    @staticmethod
    def _check_export_config(export_config):
        if 'target' not in export_config:
            raise ExportServiceError('Target configuration not found')
        target = export_config['target']
        if 'type' not in target:
            raise ExportServiceError('Type not found in target configuration')
        if target['type'] == 's3':
            if 'config' not in target:
                raise ExportServiceError('Empty configuration not supported for S3 target')
            if 'bucket' not in target['config']:
                raise ExportServiceError('Bucket required for S3 target')

    @staticmethod
    def _extension_to_content_type(filename):
        regex = r'([^\s+])(\.jpg|\.jpeg|\.png|\.pdf|\.svg|\.json$)'
        r = re.search(regex, filename)
        if not regex:
            raise ExportServiceError('Can not find extension from filename: {}'.format(filename))
        ext = r.group(2)
        if ext.endswith('jpg') or ext.endswith('jpeg'):
            return 'image/jpeg'
        elif ext.endswith('png'):
            return 'image/png'
        elif ext.endswith('pdf'):
            return 'application/pdf'
        elif ext.endswith('svg'):
            return 'image/svg+xml'
        elif ext.endswith('json'):
            return 'application/json'
        return None

    def _upload_to_s3(self, bucket_id, filename):
        exists = self.s3.lookup(bucket_id)
        if not exists:
            bucket = self.s3.create_bucket(bucket_id, location=Location.EU)
        else:
            bucket = self.s3.get_bucket(bucket_id)
        k = Key(bucket)
        k.key = filename
        k.set_contents_from_filename('/tmp/{}'.format(filename))
        content_type = self._extension_to_content_type(filename)
        k.set_metadata('Content-Type', content_type)
        k.set_acl('public-read')
        url = k.generate_url(expires_in=0, query_auth=False)
        return url

    def _call_inkscape(self, svg_string, filename, _format, dpi):
        with open('/tmp/input.svg', 'w') as f:
            f.write(svg_string)

        if _format == 'png':
            _log.info('Exporting as PNG {} to local filesystem'.format(filename))
            cmd = ['inkscape', '/tmp/input.svg', '--export-png=/tmp/{}'.format(filename), 
            '--without-gui', '--export-area-drawing', '--export-dpi={}'.format(str(dpi))]
        elif _format == 'pdf':
            _log.info('Exporting as PDF {} to local filesystem'.format(filename))
            cmd = ['inkscape', '/tmp/input.svg', '--export-pdf=/tmp/{}'.format(filename), 
            '--without-gui', '--export-area-drawing', '--export-dpi={}'.format(str(dpi))]
        elif _format == 'svg':
            _log.info('Exporting as Plain SVG {} to local filesystem'.format(filename))
            cmd = ['inkscape', '/tmp/input.svg', '--export-plain-svg=/tmp/{}'.format(filename), 
            '--without-gui', '--export-area-drawing', '--export-text-to-path']
        else:
            raise ExportServiceError('Format {} not supported'.format(_format))

        subprocess.run(cmd)

    def _call_convert(self, svg_string, filename, dpi):
        with open('/tmp/input.svg', 'w') as f:
            f.write(svg_string)
        _log.info('Exporting {} to local filesystem'.format(filename))
        cmd = ['convert', '-density', str(dpi), '/tmp/input.svg', '/tmp/{}'.format(filename)]
        try:
            subprocess.run(cmd)
        except:
            raise ExportServiceError('An error occured while running convert command')

    @rpc
    def export(self, svg_string, filename, export_config, dpi = 72):
        self._check_export_config(export_config)
        self._call_convert(svg_string, filename, dpi)
        if export_config['target']['type'] == 's3':
            bucket_id = export_config['target']['config']['bucket']
            _log.info('Uploading {} on S3 (bucket: {})'.format(filename, bucket_id))
            url = self._upload_to_s3(bucket_id, filename)
        return url

    @rpc
    def upload(self, content, filename, export_config):
        self._check_export_config(export_config)
        with open('/tmp/{}'.format(filename), 'w') as f:
            f.write(content)
        if export_config['target']['type'] == 's3':
            bucket_id = export_config['target']['config']['bucket']
            _log.info('Uploading {} on S3 (bucket: {})'.format(filename, bucket_id))
            url = self._upload_to_s3(bucket_id, filename)
        return url

    @rpc
    def text_to_path(self, svg_string):
        self._call_inkscape(svg_string, 'export.svg', 'svg', None)

        with open('/tmp/export.svg', 'r') as f:
            converted = f.read()

        return converted
