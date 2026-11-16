import json

def lambda_handler(event, context):
    print("Received backend request event:", json.dumps(event))
    
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({
            'status': 'success',
            'message': 'Hello from AI Creative Studio Backend (VPC Layer Active!)'
        })
    }
