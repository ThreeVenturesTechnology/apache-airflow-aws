# Apache-AirFlow-AWS
A baseline framework for deploying Apache Airflow in AWS.

Setup to run Airflow in AWS ECS (Elastic Container Service) Fargate with autoscaling enabled for all services. 
All infrastructure is created with Cloudformation and secrets are managed by AWS Secrets Manager.

For an indepth deployment guide, please read [this blog post](https://threeventures.com/how-to-deploy-apache-airflow-using-aws-fargate/).

# Features
* Control all Airflow environments from a single `service.yml` file.
* Metadata DB Passwords Managed with AWS Secrets Manager.
* Autoscaling enabled and configurable for all Airflow sub-services (workers, webserver, scheduler)
* Automatically deploy with codebuild.

## Preparing for Deployment
* Create an AWS IAM User for the infrastructure deployment. A policy is provided for an IAM user at `airflow.cli-user.policy.json`. 
* Install AWS CLI running `pip install awscli`
* Install Docker
* Setup your IAM User credentials for the AWS CLI
* Create a virtual environment
	```shell script
	pip install awscli
	virtualenv venv
	source venv/bin/activate
	pip install -r requirements.txt
	```
* Setup env variables
	```shell script
	export AWS_REGION=us-east-1;
	export AWS_PROFILE=my_aws_profile;
	export ENVIRONMENT=dev;
	```
## Setup for CI/CD:
* Create branch in your GitHub repository with name same as branch variable in service.yml. This should match the ENVIRONMENT shell variable.
* Create copy of buildspec.example.yml with name as buildspec.ENVIRONMENT.yml
* Create Codestar connection to your GitHub repository.
* Add the ARN of codestar connection, GitHub URL and GitHub path to your `service.yml` file 

### Deploy Airflow 
```shell script
make airflow-init
```
> After deploying, you likely will need to wait 30 minutes or so.

Look for AirflowWebServerEndpoint in your terminal. This is how you can access the AirFlow environment using the browser.
```
    "cfn-airflow-webserver": [
        {
            "OutputKey": "AirflowWebServerEndpoint",
            "OutputValue": "airflow-dev-webserver-alb-1234567890.us-east-1.elb.amazonaws.com"
        }
    ],
```

To rebuild Airflow Docker Image and push it to ECR (without infrastructure changes), run:
```shell script
make airflow-push-image
```

To destroy your stack run the following command:
```shell script
make airflow-destroy
```

### Update a Dag on AWS
If You want to update dags without using CI/CD type:
```shell script
make airflow-push-image
```

### CI/CD
You created a branch with name same as the Environment variable, updated buildspec.yml file name,
and created proper ARN connection. Pushing to branch will release your code updates, build a new docker image, and update the tasks in Fargate.

## Additional Image Commands 
Need to add additional commands to run when an image is built? Add commands into `/extra_commands.sh`.

## Adding Environment Variables
If you need to add new environment variables you should add them into .env file and use the command `make airflow-update-stack` to update your environment variables only.

## Adding an SSL
If you want to add an SSL you can add the certificates ARN to your `service.yml` file for each environment. Once your deployment in complete, use the `AirflowWebServerEndpoint` output from your terminal to create your DNS records in Route53.

### Managing Environments with `service.yaml`
If You look into service.yml file, You will find out that the tree starts with a "default" tag. That is the setting that any initial deployment will always default to if it does not find a config key matching the shell variable `ENVIRONMENT`. Create your own config per enviroment by copy/pasting the default config to the bottom of file and change "default" to your environment name.
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
> Use service.sample.yaml as a baseline


*Inspired by the work done by [andresionek91](https://github.com/andresionek91/airflow-autoscaling-ecs/blob/master/README.md)*
