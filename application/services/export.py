from logging import getLogger
import subprocess
import re
from nameko.rpc import rpc
from nameko.dependency_providers import DependencyProvider
from boto.s3.key import Key
from boto.s3.connection import Location
from boto.s3.cors import CORSConfiguration
from application.dependencies.s3 import S3


_log = getLogger(__name__)


class ErrorHandler(DependencyProvider):

    def worker_result(self, worker_ctx, res, exc_info):
        if exc_info is None:
            return

        exc_type, exc, tb = exc_info
        _log.error(str(exc))


class ExportServiceError(Exception):
    pass


class ExportService(object):
    name = 'exporter'

    s3 = S3()
    error = ErrorHandler()

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
    def _extract_extension(filename):
        regex = r'([^\s+])(\.jpg|\.jpeg|\.png|\.pdf|\.svg|\.json|\.html$)'
        r = re.search(regex, filename)
        if not regex:
            raise ExportServiceError('Can not find extension from filename: {}'.format(filename))
        ext = r.group(2)
        return ext.replace(".", "")

    @staticmethod
    def _extension_to_content_type(filename):
        ext = ExportService._extract_extension(filename)
        content_types = {
            'jpg': 'image/jpeg',
            'png': 'image/png',
            'pdf': 'application/pdf',
            'svg': 'image/svg+xml',
            'json': 'application/json',
            'html': 'text/html'
        }
        return content_types.get(ext)

    @staticmethod
    def _get_cors_rules():
        cfg = CORSConfiguration()
        cfg.add_rule('GET', '*')
        return cfg

    def _upload_to_s3(self, bucket_id, filename):
        exists = self.s3.lookup(bucket_id)
        if not exists:
            bucket = self.s3.create_bucket(bucket_id, location=Location.EU)
            bucket.set_cors(ExportService._get_cors_rules())
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
        tmp_filename = self._save_on_local_filesystem(svg_string, '/tmp/input.svg')
        cmd = ['convert', '-density', str(dpi), tmp_filename, '/tmp/{}'.format(filename)]
        try:
            subprocess.run(cmd)
        except:
            raise ExportServiceError('An error occured while running convert command')

    def _save_on_local_filesystem(self, content, target_filename):
        _log.info('Exporting {} to local filesystem'.format(target_filename))
        with open(target_filename, 'w') as f:
            f.write(content)
        return target_filename
    
    def _upload_result(self, export_config, filename):
        if export_config['target']['type'] == 's3':
            bucket_id = export_config['target']['config']['bucket']
            _log.info('Uploading {} on S3 (bucket: {})'.format(filename, bucket_id))
            url = self._upload_to_s3(bucket_id, filename)
        return url

    @rpc
    def export(self, svg_string, filename, export_config, dpi = 72):
        self._check_export_config(export_config)
        ext = ExportService._extract_extension(filename)
        if ext in ('jpg', 'jpeg', 'png', 'pdf'):
            self._call_convert(svg_string, filename, dpi)
        else:
            self._save_on_local_filesystem(svg_string, '/tmp/{}'.format(filename))
        return self._upload_result(export_config, filename)

    @rpc
    def upload(self, content, filename, export_config):
        self._check_export_config(export_config)
        self._save_on_local_filesystem(content, '/tmp/{}'.format(filename))
        return self._upload_result(export_config, filename)

    @rpc
    def text_to_path(self, svg_string):
        self._call_inkscape(svg_string, 'export.svg', 'svg', None)

        with open('/tmp/export.svg', 'r') as f:
            converted = f.read()

        return converted
