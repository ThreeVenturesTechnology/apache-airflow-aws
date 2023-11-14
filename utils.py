import os

from dotenv import dotenv_values
from jinja2 import Template
from yaml import safe_load
import boto3
from cryptography.fernet import Fernet
import logging
import json
from uuid import uuid4
from airflow import settings
from airflow.models import Connection

logging.basicConfig(level=logging.INFO)
logging.getLogger('botocore').setLevel(logging.CRITICAL)


def set_env_variables():
    """
    Boto3 sometimes requires default region in addition to aws_region
    """
    os.environ['AWS_DEFAULT_REGION'] = os.environ.get('AWS_REGION', '')


def _get_abs_path(path) -> str:
    """
    Responsible for returning current path
    """
    return os.path.join(os.path.dirname(os.path.realpath(__file__)), path)


def get_service_variables() -> dict:
    """
    Responsible for getting service variables taking into account current variable
    :return:
    """
    try:
        environment = os.environ['ENVIRONMENT']
    except KeyError:
        raise KeyError(f'Environment variable ENVIRONMENT not found. Please set it up before starting.')

    with open(_get_abs_path("service.yml")) as f:
        service_config = safe_load(f)
    if environment in service_config:
        return service_config[environment]
    return service_config['default']


def get_formatted_dotenv() -> str:
    """
    Responsible for returning dotenv file variables in format viable to insert into .env
    """
    config = dotenv_values(".env")
    yml_config = ""
    for key in config:
        yml_config += f'- Name: {key}\n  Value: {config[key]}\n'
    return yml_config

def render_template(template) -> str:
    """
    Responsible for rendering variables into cloudformation yml files
    :param template:
    :return:
    """
    service_config = get_service_variables()
    with open(_get_abs_path("extra_commands.sh")) as c:
        initial_commands = c.read()

    return Template(template).render({**service_config,
                                      **dict(os.environ),
                                      **{"initial_command": initial_commands,
                                         "custom_env_variables": get_formatted_dotenv()}})


def create_fernet_key():
    """
    Try to find fernet key in AWS Secrets Manager.
    If resource does not exist, create a new key.
    Set key as environment variable to be used by CF template.
    """
    set_env_variables()
    client = boto3.client('secretsmanager')

    try:
        response = client.get_secret_value(SecretId=render_template('{{ serviceName }}-{{ ENVIRONMENT }}-fernet-key'))
        os.environ['FERNET_KEY'] = json.loads(response['SecretString'])['fernet_key']
        logging.info('FERNET KEY found in Secrets Manager.')
    except client.exceptions.ResourceNotFoundException:
        fernet_key = Fernet.generate_key().decode()
        os.environ['FERNET_KEY'] = fernet_key
        logging.info(
            'FERNET KEY not found in Secrets Manager. New key created. It will be uploaded to Secrets Manager.')


def create_default_tags():
    tags_template = '''[
        {"Key": "Owner","Value": "{{ owner }}"},
        {"Key": "Service", "Value": "{{ serviceName }}"},
        {"Key": "Environment", "Value": "{{ ENVIRONMENT }}"}
        ]'''
    tags = json.loads(render_template(tags_template))
    return tags


def get_aws_account_id():
    client = boto3.client("sts")
    return client.get_caller_identity()["Account"]


def generate_hash(n):
    return str(uuid4().hex[:n])


def check_environment_variables():
    """
    Responsible for checking if we set proper environment variables
    """

    for env_var in ['AWS_REGION', 'ENVIRONMENT', 'AWS_PROFILE']:
        try:
            os.environ[env_var]
        except KeyError:
            raise KeyError(f'Environment variable {env_var} not found. Please set it up before starting.')
    service_config = get_service_variables()
    git_fields = ('fullRepositoryName', 'location', 'codestarArn')
    for config_var in git_fields:
        try:
            if not service_config['github'][config_var]:
                raise KeyError
        except KeyError:
            exit(f'Config variable {config_var} not set. Please set it in your service.yml before starting.')

    with open(_get_abs_path("service.yml")) as f:
        service_config = safe_load(f)
    if os.environ['ENVIRONMENT'] in service_config:
        print(f'{os.environ["ENVIRONMENT"]} environment service variables loaded.')
    else:
        print(f'Proceeding with "default" service variables.')



def create_connection(conn_id, conn_type, host='', login='', pwd='', port=None, desc='', extra=''):
    """
    Responsible for creating airflow connection
    """
    set_env_variables()
    conn = Connection(conn_id=conn_id,
                      conn_type=conn_type,
                      host=host,
                      login=login,
                      password=pwd,
                      port=port,
                      description=desc,
                      extra=extra)
    session = settings.Session()
    conn_name = session.query(Connection).filter(Connection.conn_id == conn.conn_id).first()
    if str(conn_name) == str(conn.conn_id):
        logging.warning(f"Connection {conn.conn_id} already exists")
        return None

    session.add(conn)
    session.commit()
    logging.info(f'Connection {conn_id} is created')
    return conn


def run_init_task():
    """
    Runs init tasks definition, should be run after all stacks are created
    """
    set_env_variables()
    service_config = get_service_variables()
    ecs = boto3.client('ecs')
    ec2 = boto3.client('ec2')
    environment = os.getenv('ENVIRONMENT')

    cluster_name = f'{service_config["serviceName"]}-{environment}-ecs-cluster'
    subnets = ec2.describe_subnets()
    task_definition = f'{service_config["serviceName"]}-{environment}-init-task-definition'
    scheduler_service_name = f'{service_config["serviceName"]}-{environment}-scheduler'
    webserver_service_name = f'{service_config["serviceName"]}-{environment}-webserver'
    workers_service_name = f'{service_config["serviceName"]}-{environment}-workers'
    filtered_subnets = []
    for subnet in subnets['Subnets']:
        counter = 0
        if 'Tags' in subnet:
            for tag in subnet['Tags']:
                if tag == {'Key': 'Environment', 'Value': environment} or\
                        tag == {'Key': 'Service', 'Value': service_config["serviceName"]}:
                    counter += 1
                if counter == 2:
                    filtered_subnets.append(subnet['SubnetId'])
                    break
    ecs.run_task(cluster=cluster_name, launchType='FARGATE', taskDefinition=task_definition, count=1,
                 platformVersion='LATEST', networkConfiguration={'awsvpcConfiguration': {'subnets': filtered_subnets,
                                                                                         'assignPublicIp': 'ENABLED'}}
                 )
    update_services_desired_count()


def update_services_desired_count():
    set_env_variables()
    service_config = get_service_variables()
    ecs = boto3.client('ecs')
    environment = os.getenv('ENVIRONMENT')

    cluster_name = f'{service_config["serviceName"]}-{environment}-ecs-cluster'
    scheduler_service_name = f'{service_config["serviceName"]}-{environment}-scheduler'
    webserver_service_name = f'{service_config["serviceName"]}-{environment}-webserver'
    workers_service_name = f'{service_config["serviceName"]}-{environment}-workers'
    ecs.update_service(cluster=cluster_name, service=scheduler_service_name,
                       desiredCount=service_config["service"]["scheduler"]["desiredCount"])
    ecs.update_service(cluster=cluster_name, service=webserver_service_name,
                       desiredCount=service_config["service"]["webserver"]["desiredCount"])
    ecs.update_service(cluster=cluster_name, service=workers_service_name,
                       desiredCount=service_config["service"]["workers"]["desiredCount"])
