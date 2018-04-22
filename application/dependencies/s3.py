import boto
from nameko.extensions import DependencyProvider


class S3(DependencyProvider):
	

	def setup(self):
		self.connection = boto.connect_s3()

	def stop(self):
		self.connection.close()
		del self.connection

	def kill(self):
		self.connection.close()
		del self.connection

	def get_dependency(self, worker_ctx):
		return self.connection