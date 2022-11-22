# Apache-AirFlow-AWS
A baseline framework for deploying Apache Airflow in AWS.

Setup to run Airflow in AWS ECS (Elastic Container Service) Fargate with autoscaling enabled for all services. 
All infrastructure is created with Cloudformation and Secrets are managed by AWS Secrets Manager.

## Requirements
* Create an AWS IAM User for the infrastructure deployment, in `airflow.cli-user.policy.json` there is policy for that user  if you do not want to creat admin user
* Install AWS CLI running `pip install awscli`
* Install Docker
* Setup your IAM User credentials inside `~/.aws/config`
```
    [profile my_aws_profile]
    aws_access_key_id = <my_access_key_id> 
    aws_secret_access_key = <my_secret_access_key>
    region = us-east-1
```
* Create a virtual environment
* Setup env variables
```shell script
	export AWS_REGION=us-east-1;
	export AWS_PROFILE=my_aws_profile;
	export ENVIRONMENT=dev;
```
## Setup for CI/CD:
* Create branch in You github repository with name same as branch variable in service.yml
* Create copy of buildspec.example.yml with name as buildspec.“ENVIRONMENT”.yml
* Create Codestar connection to your github repository
* Add arn of codestar connection, github url and github path to your “service.yml” file 

## Deploy Airflow 
```shell script
make airflow-init
```

To rebuild Airflow Docker Image and push it to ECR (without infrastructure changes), run:
```shell script
make airflow-push-image
```

To destroy your stack run the following command:
```shell script
make airflow-destroy
```

## Update a Dag on AWS
If You want to update dags not without using CI/CD type:
```shell script
make airflow-push-image
```

### CI/CD
Now when everything went ok, the infrastructure for continuous integration  should be working.
You created a branch with name same as Environment variable, updated buildspec.yml file name,
and created proper arn connection. Pushing to branch will release code update, docker image 
will be rebuilt, server restarted and Your changes will be automatically applied to your stage!.

## Adding initial commands 
If you want to add comments to init, usually that will be to create
connections insert bash instructions into extra_commands.sh
You can use make airflow-run-commands to run them
## Adding additional environment variables
If You need to add new environment variables you should add them into .env file and use command "make airflow-update-stack"
.env variables should be kept in secret, that is way you should not push them in branch to trigger codebuild.

## Adding ssl
If you want to add ssl you can add certificate to your service.yml file.
Next redirect your domain in amazon route53 hosted zones in aws.
Note: Load balancer address will be still available, 

# Features
* Control all Airflow infrastructure from a single `service.yml` file.
* Metadata DB Passwords Managed with AWS Secrets Manager.
* Autoscaling enabled and configurable for all Airflow sub-services (workers, webserver, scheduler)
* Automatically deploy with codebuild to your branch

### Adjust many infrastructure configs directly on Service.yml: 
If You look into service.yml file, You will find out that the tree starts with a "default" tag. That is the setting that
app will always default to if it does not find config as environment variable.
If You wish to set Your own config copy&past default config to the bottom of file and change "default" to Your environment name.
hint: look into service.sample.yml
```yaml
default:
  ""...""
  workers:
    port: 8793
    cpu: 1024
    memory: 2048
    desiredCount: 2
    autoscaling:
      maxCapacity: 8
      minCapacity: 2
      cpu:
        target: 70
        scaleInCooldown: 60
        scaleOutCooldown: 120
      memory:
        target: 70
        scaleInCooldown: 60
        scaleOutCooldown: 120
```


Look for AirflowWebServerEndpoint on outputs logged to your terminal.
```
    "cfn-airflow-webserver": [
        {
            "OutputKey": "AirflowWebServerEndpoint",
            "OutputValue": "airflow-dev-webserver-alb-1234567890.us-east-1.elb.amazonaws.com"
        }
    ],
```

*Inspired by the work done by [andresionek91](https://github.com/andresionek91/airflow-autoscaling-ecs/blob/master/README.md)*