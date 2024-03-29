import boto3
import os
import re
import json
import logging
from botocore.exceptions import ClientError
import click
from yaml import safe_load

from utils import _get_abs_path
from utils import render_template
from utils import create_default_tags
from utils import create_fernet_key
from utils import get_aws_account_id
from utils import get_service_variables
from utils import update_services_desired_count

ENVIRONMENT = os.environ['ENVIRONMENT']
os.environ['AWS_DEFAULT_REGION'] = os.environ['AWS_REGION']

logging.basicConfig(level=logging.INFO)
cloudformation_client = boto3.client('cloudformation')
cloudformation_resource = boto3.resource('cloudformation')
s3_client = boto3.client('s3')
ecs_client = boto3.client('ecs')


# Cloud formation prefix
service_config = get_service_variables()
cloud_formation_prefix = f'{service_config["serviceName"]}-{ENVIRONMENT}-'


def get_cloudformation_templates(reverse=False) -> list:
    """
    Responsible for getting cloud formation stack files
    """
    cf_templates = []
    files = os.listdir(_get_abs_path("cloudformation"))
    files.sort(reverse=reverse)
    create_fernet_key()

    for filename in files:
        path = _get_abs_path("cloudformation") + "/" + filename
        with open(path) as f:
            template_body = f.read()
        logging.info(f'Rendering template {filename}')
        template_body = render_template(template_body)
        cf_template = {
            'stack_name': cloud_formation_prefix + re.search('(?<=_)(.*)(?=.yml.j2)', filename).group(1),
            'template_body': template_body,
            'filename': filename
         }
        cf_templates.append(cf_template)

    return cf_templates


def validate_templates():
    """
    Responsible for checking if stack templates do not have errors.
    """
    cf_templates = get_cloudformation_templates()
    for cf_template in cf_templates:
        logging.info('Validating CF template {}'.format(cf_template['filename']))
        cloudformation_client.validate_template(
            TemplateBody=cf_template['template_body']
        )


def get_existing_stacks() -> list:
    """
    Responsible for reading current stack in cloud
    """
    response = cloudformation_client.list_stacks(
        StackStatusFilter=['CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE']
    )

    return [stack['StackName'] for stack in response['StackSummaries']]


def update_stack(stack_name, template_body, **kwargs):
    """
    Responsible for updating cloud stacks
    """
    try:
        cloudformation_client.update_stack(
            StackName=stack_name,
            Capabilities=['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM'],
            TemplateBody=template_body,
            Tags=create_default_tags()
        )
        update_services_desired_count()

    except ClientError as e:
        if 'No updates are to be performed' in str(e):
            logging.info(f'SKIPPING UPDATE: No updates to be performed at stack {stack_name}')
            return e

    cloudformation_client.get_waiter('stack_update_complete').wait(
        StackName=stack_name,
        WaiterConfig={'Delay': 5, 'MaxAttempts': 600}
    )

    cloudformation_client.get_waiter('stack_exists').wait(StackName=stack_name)
    logging.info(f'UPDATE COMPLETE')


def create_stack(stack_name, template_body, **kwargs):
    """
    Responsible for creation of cloud stacks
    """
    cloudformation_client.create_stack(
        StackName=stack_name,
        TemplateBody=template_body,
        Capabilities=['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM'],
        TimeoutInMinutes=30,
        OnFailure='ROLLBACK',
        Tags=create_default_tags()
    )

    cloudformation_client.get_waiter('stack_create_complete').wait(
        StackName=stack_name,
        WaiterConfig={'Delay': 5, 'MaxAttempts': 600}
    )

    cloudformation_client.get_waiter('stack_exists').wait(StackName=stack_name)
    logging.info(f'CREATE COMPLETE')


def create_or_update_stacks(is_foundation):
    """
    Responsible for figuring out if cloud stack should be created or updated
    """
    cf_templates = get_cloudformation_templates()
    cf_templates = filter_infra_templates(cf_templates, is_foundation)
    existing_stacks = get_existing_stacks()

    for cf_template in cf_templates:
        if cf_template['stack_name'] in existing_stacks:
            logging.info('UPDATING STACK {stack_name}'.format(**cf_template))
            update_stack(**cf_template)
        else:
            logging.info('CREATING STACK {stack_name}'.format(**cf_template))
            create_stack(**cf_template)


def destroy_stacks():
    """
    Responsible for triggering all cloud stacks deletion.
    """
    if not click.confirm('You are about to delete all your Airflow Infrastructure. Do you want to continue?',
                         default=False):
        return
    cf_templates = get_cloudformation_templates(reverse=True)
    existing_stacks = get_existing_stacks()

    for cf_template in cf_templates:
        if cf_template['stack_name'] in existing_stacks:
            logging.info('DELETING STACK {stack_name}'.format(**cf_template))
            delete_stack(**cf_template)


def delete_stack(stack_name, **kwargs):
    """
    Responsible for deletion of single stack
    """
    cloudformation_client.delete_stack(
        StackName=stack_name
    )

    cloudformation_client.get_waiter('stack_delete_complete').wait(
        StackName=stack_name,
        WaiterConfig={'Delay': 5, 'MaxAttempts': 600}
    )

    logging.info(f'DELETE COMPLETE')


def filter_infra_templates(cf_templates, is_foundation):
    """
    Responsible for deletion of single stack
    """
    if is_foundation:
        return [x for x in cf_templates if 'airflow' not in x['stack_name']]
    else:
        return [x for x in cf_templates if 'airflow' in x['stack_name']]


def update_ecs_service(airflow_service):
    """
    Responsible for updating ecs
    """
    aws_account_id = get_aws_account_id()
    ecs_service = render_template('{{ serviceName }}-{{ ENVIRONMENT }}-{airflow_service}').format(
        airflow_service=airflow_service)
    ecs_cluster = render_template(
        'arn:aws:ecs:{{ AWS_REGION }}:{aws_account_id}:cluster/{{ serviceName }}-{{ ENVIRONMENT }}-ecs-cluster').format(
        aws_account_id=aws_account_id)
    logging.info(f'RESTARTING SERVICE: {ecs_service}')
    ecs_client.update_service(cluster=ecs_cluster, service=ecs_service, forceNewDeployment=True)


def restart_airflow_ecs():
    """
    Responsible for restarting ecs, but first checks if ecs services are running
    """
    cluster_name = f'{service_config["serviceName"]}-{ENVIRONMENT}-ecs-cluster'
    scheduler_service_name = f'{service_config["serviceName"]}-{ENVIRONMENT}-scheduler'
    webserver_service_name = f'{service_config["serviceName"]}-{ENVIRONMENT}-webserver'
    workers_service_name = f'{service_config["serviceName"]}-{ENVIRONMENT}-workers'

    services = ecs_client.describe_services(
        cluster=cluster_name,
        services=[
            scheduler_service_name,
            webserver_service_name,
            workers_service_name
        ]
    )

    deployed = {
        scheduler_service_name: False,
        webserver_service_name: False,
        workers_service_name: False
    }
    if services and 'services' in services:
        for service in services['services']:
            deployed[service['serviceName']] = False
            if service['runningCount'] > 0:
                deployed[service['serviceName']] = True

    if deployed[scheduler_service_name]:
        update_ecs_service('scheduler')
    if deployed[workers_service_name]:
        update_ecs_service('workers')
    if deployed[webserver_service_name]:
        update_ecs_service('webserver')


def log_outputs():
    """
    Responsible for printing out logs
    """
    cf_templates = get_cloudformation_templates(reverse=True)
    outputs = {}
    logging.info(f'\n\n\n## OUTPUTS ##')
    for cf_template in cf_templates:
        stack_name = cf_template['stack_name']
        stack = cloudformation_resource.Stack(stack_name)
        outputs = {
            stack_name: stack.outputs,
            **outputs
        }
    logging.info(json.dumps(outputs, indent=4))

    return outputs
