import docker
import logging
import os
import base64

from utils import _get_abs_path
from utils import generate_hash
from utils import get_service_variables
import boto3

logging.basicConfig(level=logging.INFO)

docker_client = docker.from_env()

ENVIRONMENT = os.environ['ENVIRONMENT']
AWS_REGION = os.environ['AWS_REGION']
os.environ['AWS_DEFAULT_REGION'] = os.environ['AWS_REGION']

service_config = get_service_variables()
ECR_REPO_NAME = f'airflow-{service_config["serviceName"]}-{ENVIRONMENT}'.lower()
IMAGE_TAG = 'latest'


class DockerException(Exception):
    pass


def connect_to_ecr():
    """
    Responsible for loggin into ECR
    :return:
    """
    client = boto3.client('ecr')
    token = client.get_authorization_token()

    logging.info(f'CONNECTED TO ECR')

    b64token = token['authorizationData'][0]['authorizationToken'].encode('utf-8')
    username, password = base64.b64decode(b64token).decode('utf-8').split(':')
    registry = token['authorizationData'][0]['proxyEndpoint']
    docker_client.login(username=username, password=password, registry=registry)

    return registry


def build_image():
    """
    Responsible for building image based on Makefile
    :return:
    """

    logging.info(f'BUILDING IMAGE: {ECR_REPO_NAME}:{IMAGE_TAG}')
    image, build_log = docker_client.images.build(path=_get_abs_path(''), rm=True, tag=f'{ECR_REPO_NAME}:{IMAGE_TAG}')

    for log in build_log:
        if log.get('stream'):
            logging.info(log.get('stream'))

    return image


def tag_and_push_to_ecr(image, tag):
    """
    Responsible for pushing the newest docker image to ecr
    """
    registry = connect_to_ecr()
    logging.info(f'Pushing image to ECR: {ECR_REPO_NAME}:{tag}')
    ecr_repo_name = '{}/{}'.format(registry.replace('https://', ''), ECR_REPO_NAME)
    image.tag(ecr_repo_name, tag)
    push_log = docker_client.images.push(ecr_repo_name, tag=tag)

    if 'errorDetail' in push_log:
        logging.error(push_log)
        raise DockerException()
    logging.info(push_log)


def update_airflow_image():
    """
    Responsible for creating docker image and invokes pushing new image to ecr repository
    """
    image = build_image()
    tag_and_push_to_ecr(image, IMAGE_TAG)
    hash_tag = generate_hash(16)
    tag_and_push_to_ecr(image, hash_tag)


def remove_ecr_images():
    """
    Responsible for deleting all images from ecr
    """
    print('Removing ecr images')
    client = boto3.client('ecr')
    response = client.list_images(repositoryName=ECR_REPO_NAME)
    images_list = [image for image in response['imageIds']]
    client.batch_delete_image(repositoryName=ECR_REPO_NAME, imageIds=images_list)


def clear_artifacts_bucket():
    """
    Responsible for deleting all files in codebuild artifacts folder
    """
    print('Removing artifacts')
    bucket_name = f'{service_config["serviceName"]}-codebuild-artifacts-{ENVIRONMENT}'.lower()
    s3 = boto3.resource("s3")
    bucket = s3.Bucket(bucket_name)
    bucket.objects.delete()
