from logging import getLogger
import subprocess
import re
import uuid
import os
from nameko.rpc import rpc
from nameko.dependency_providers import DependencyProvider
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
                raise ExportServiceError(
                    'Empty configuration not supported for S3 target')
            if 'bucket' not in target['config']:
                raise ExportServiceError('Bucket required for S3 target')

    @staticmethod
    def _extract_extension(filename):
        regex = r'([^\s+])(\.jpg|\.jpeg|\.png|\.pdf|\.pdfx|\.svg|\.json|\.html)$'
        r = re.search(regex, filename)
        if not regex:
            raise ExportServiceError(
                'Can not find extension from filename: {}'.format(filename))
        ext = r.group(2)
        return ext.replace(".", "")

    @staticmethod
    def _extension_to_content_type(filename):
        ext = ExportService._extract_extension(filename)
        content_types = {
            'jpg': 'image/jpeg',
            'png': 'image/png',
            'pdf': 'application/pdf',
            'pdfx': 'application/pdf',
            'svg': 'image/svg+xml',
            'json': 'application/json',
            'html': 'text/html'
        }
        return content_types.get(ext)

    def _upload_to_s3(self, bucket_id, filename):
        self.s3.create_bucket(bucket_id)
        content_type = ExportService._extension_to_content_type(filename)
        return self.s3.upload(bucket_id, f'/tmp/{filename}', filename, content_type)

    def _call_inkscape(self, svg_string, filename, _format, dpi, text_to_path):
        tmp_filename = self._save_on_local_filesystem(
            svg_string, '/tmp/{}.svg'.format(str(uuid.uuid4())))
        
        if _format == 'png':
            _log.info('Exporting as PNG {} to local filesystem'.format(filename))
            cmd = ['inkscape', tmp_filename, '--export-png=/tmp/{}'.format(filename),
                   '--without-gui', '--export-area-drawing', '--export-dpi={}'.format(str(dpi))]
        elif _format == 'pdf':
            _log.info('Exporting as PDF {} to local filesystem'.format(filename))
            cmd = ['inkscape', tmp_filename, '--export-pdf=/tmp/{}'.format(filename),
                   '--without-gui', '--export-area-drawing']
        elif _format == 'svg':
            _log.info(
                'Exporting as Plain SVG {} to local filesystem'.format(filename))
            cmd = ['inkscape', tmp_filename, '--export-plain-svg=/tmp/{}'.format(filename), '--without-gui', '--export-area-drawing', '--export-text-to-path']\
                if text_to_path else ['inkscape', tmp_filename, '--export-plain-svg=/tmp/{}'.format(filename), '--without-gui', '--export-area-drawing']
        else:
            raise ExportServiceError('Format {} not supported'.format(_format))

        subprocess.run(cmd)

        return filename

    @staticmethod
    def _build_convert_command(tmp_filename, filename, dpi, color_space, profile):
        cmd = ['convert', '-density', str(dpi)]
        if color_space is None:
            return cmd + [tmp_filename] + ['/tmp/{}'.format(filename)]
        return cmd + ['-profile'] + ['/service/profiles/{}/{}.icc'.format(color_space, profile)] + [tmp_filename] + ['/tmp/{}'.format(filename)]

    def _call_convert(self, svg_string, filename, dpi, color_space, profile):
        tmp_filename = self._save_on_local_filesystem(
            svg_string, '/tmp/{}.svg'.format(str(uuid.uuid4())))
        cmd = ExportService._build_convert_command(
            tmp_filename, filename, dpi, color_space, profile)
        _log.info('Command args: {}'.format(cmd))
        try:
            subprocess.run(cmd)
        except:
            raise ExportServiceError(
                'An error occured while running convert command')

        return filename

    def _call_ghostscript(self, input_filename, filename, color_space, profile, print_):
        if not print_:
            if color_space == 'cmyk':
                cmd = [
                    'gs',
                    '-o',
                    '/tmp/{}'.format(filename),
                    '-sDEVICE=pdfwrite',
                    '-dOverrideICC=true',
                    '-sOutputICCProfile=/service/profiles/{}/{}.icc'.format(color_space, profile),
                    '-sColorConversionStrategy=CMYK',
                    '-dProcessColorModel=/DeviceCMYK',
                    '-dRenderIntent=3',
                    '-dDeviceGrayToK=true',
                    '/tmp/{}'.format(input_filename)]
            else:
                cmd = [
                    'gs',
                    '-o',
                    '/tmp/{}'.format(filename),
                    '-sDEVICE=pdfwrite',
                    '-dOverrideICC=true',
                    '-sOutputICCProfile=/service/profiles/{}/{}.icc'.format(color_space, profile),
                    '/tmp/{}'.format(input_filename)]
        else:
            if color_space != 'cmyk':
                raise ExportServiceError('Color space {} not supported for printed PDF!'.format(color_space))
            cmd = [
                'gs',
                '-o',
                '/tmp/{}'.format(filename),
                '-sDEVICE=pdfwrite',
                '-dOverrideICC=true',
                '-sOutputICCProfile=/service/profiles/{}/{}.icc'.format(color_space, profile),
                '-sColorConversionStrategy=CMYK',
                '-dProcessColorModel=/DeviceCMYK',
                '-dRenderIntent=3',
                '-dDeviceGrayToK=true',
                '-dPDFX',
                '-dPDFSETTINGS=/printer',
                '/tmp/{}'.format(input_filename)]
        _log.info('Command args: {}'.format(cmd))
        try:
            subprocess.run(cmd)
        except:
            raise ExportServiceError(
                'An error occured while running ghostscript command')

    def _save_on_local_filesystem(self, content, target_filename):
        _log.info('Exporting {} to local filesystem'.format(target_filename))
        with open(target_filename, 'w') as f:
            f.write(content)
        return target_filename

    def _upload_result(self, export_config, filename):
        if export_config['target']['type'] == 's3':
            bucket_id = export_config['target']['config']['bucket']
            _log.info('Uploading {} on S3 (bucket: {})'.format(
                filename, bucket_id))
            url = self._upload_to_s3(bucket_id, filename)
        return url

    @rpc
    def export(self, svg_string, filename, export_config, dpi=72, color_space=None, profile=None):
        self._check_export_config(export_config)
        ext = ExportService._extract_extension(filename)
        if ext in ('jpg', 'jpeg', 'png'):
            self._call_convert(svg_string, filename, dpi, color_space, profile)
        elif ext == 'svg':
            self._call_inkscape(svg_string, filename, 'svg', dpi, True)
        elif ext == 'pdf':
            first_pdf = self._call_inkscape(svg_string, '_' + filename, 'pdf', dpi, True)
            self._call_ghostscript('_' + filename, filename, color_space, profile, False)
            os.remove('/tmp/{}'.format(first_pdf))
        elif ext == 'pdfx':
            clean_filename = filename[:-1]
            first_pdf = self._call_inkscape(svg_string, '_' + clean_filename, 'pdf', dpi, True)
            self._call_ghostscript('_' + clean_filename, clean_filename, color_space, profile, True)
            os.remove('/tmp/{}'.format(first_pdf))
        else:
            self._save_on_local_filesystem(
                svg_string, '/tmp/{}'.format(filename))
        url = self._upload_result(export_config, filename)
        
        _log.info('Removing tmp file ...')
        os.remove('/tmp/{}'.format(filename))
        return url

    @rpc
    def upload(self, content, filename, export_config):
        self._check_export_config(export_config)
        self._save_on_local_filesystem(content, '/tmp/{}'.format(filename))
        return self._upload_result(export_config, filename)

    @rpc
    def text_to_path(self, svg_string):
        self._call_inkscape(svg_string, 'export.svg', 'svg', None, True)

        with open('/tmp/export.svg', 'r') as f:
            converted = f.read()

        return converted

    @rpc
    def to_plain_svg(self, svg_string):
        self._call_inkscape(svg_string, 'export.svg', 'svg', None, False)

        with open('/tmp/export.svg', 'r') as f:
            converted = f.read()

        return converted
