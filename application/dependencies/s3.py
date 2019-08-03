import boto3
import botocore
from nameko.extensions import DependencyProvider


class S3Handler(object):

    def __init__(self, key_id, secret_key, region):
        self.resource = boto3.resource('s3', aws_access_key_id=key_id,
                                       aws_secret_access_key=secret_key, region_name=region)
        self.region = region

    def create_bucket(self, bucket_id):
        try:
            self.resource.meta.client.head_bucket(Bucket=bucket_id)
        except botocore.exceptions.ClientError:
            self.resource.meta.client.create_bucket(
                Bucket=bucket_id, CreateBucketConfiguration={'LocationConstraint': self.region})
            self.resource.meta.client.put_bucket_cors(Bucket=bucket_id, CORSConfiguration={
                'CORSRules': [{
                    'AllowedMethods': ['GET'],
                    'AllowedOrigins': ['*'],
                }]
            })

    def upload(self, bucket_id, full_filename, filename, content_type):
        config = self.resource.meta.client._client_config
        config.signature_version = botocore.UNSIGNED

        self.resource.Bucket(bucket_id).upload_file(
            Filename=full_filename, Key=filename,
            ExtraArgs={'ACL': 'public-read', 'ContentType': content_type})
        return boto3.resource('s3', config=config).meta.client.generate_presigned_url(
            'get_object', ExpiresIn=0, Params={'Bucket': bucket_id, 'Key': filename})

    def close(self):
        self.resource.close()


class S3(DependencyProvider):

    def setup(self):
        self.handler = S3Handler(
            self.container.config['AWS_ACCESS_KEY_ID'], self.container.config['AWS_SECRET_ACCESS_KEY'], 'eu-west-1')

    def stop(self):
        self.handler.close()
        del self.handler

    def kill(self):
        self.handler.close()
        del self.handler

    def get_dependency(self, worker_ctx):
        return self.handler
