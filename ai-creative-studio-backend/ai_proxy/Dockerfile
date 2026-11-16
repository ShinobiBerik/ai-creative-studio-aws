# AWS Lambda Python 3.12 Base Image (ARM64 / Apple Silicon & AWS Graviton2 compatible)
FROM public.ecr.aws/lambda/python:3.12

# Copy the AI Proxy Lambda handler into the Lambda task root (/var/task)
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/

# Default environment variables (overridden at runtime in AWS Lambda / docker-compose)
ENV AWS_DEFAULT_REGION=eu-west-2 \
    HF_TOKEN_PARAM=/ai-creative-studio/hf-token

# Set the CMD to the Lambda handler function
CMD [ "lambda_function.lambda_handler" ]
