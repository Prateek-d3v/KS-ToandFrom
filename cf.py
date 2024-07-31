import functions_framework
import os
import json
import requests
from flask import jsonify
import vertexai
from vertexai.generative_models import GenerativeModel
import constants as const
import helper as helper

# # Set the environment variable for Google Application Credentials
# os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = const.SA_ACCOUNT

# Suppress gRPC logging messages
os.environ['GRPC_VERBOSITY'] = 'ERROR'

# Optionally, suppress TensorFlow logging messages
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# Initialize Vertex AI
vertexai.init(project=const.PROJECT_ID, location=const.VERTEX_AI_LOCATION)

# Initialize the generative model
model = GenerativeModel(
    model_name=const.VERTEX_AI_MODEL,
    system_instruction=const.SYSTEM_INSTRUCTIONS
)

# Read the attributes, occasions, and relations from text files
attributes = helper.read_text_file(const.ATTRIBUTES_PATH)
occasions = helper.read_text_file(const.OCCASIONS_PATH)
relations = helper.read_text_file(const.RELATIONS_PATH)

# Load the attributes, occasions, and relations JSON files
with open('files/sqlout-attribute.json', 'r', encoding='utf-8') as f:
    attributes_data = json.load(f)
with open('files/sqlout-occasion.json', 'r', encoding='utf-8') as f:
    occasions_data = json.load(f)
with open('files/sqlout-relationship.json', 'r', encoding='utf-8') as f:
    relations_data = json.load(f)

# Define the prompt template
prompt_template = """
Attributes:
{0}
Occasions:
{1}
Relations:
{2}
Query: {3}
"""

# Function to extract IDs based on names
def get_ids(names, data, key_name):
    ids = []
    for name in names:
        for item in data:
            if item[key_name] == name:
                ids.append(item["id"])
    return ids

@functions_framework.http
def to_and_from_http(request):
    """HTTP Cloud Function.
    Args:
        request (flask.Request): The request object.
        <https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data>
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`
        <https://flask.palletsprojects.com/en/1.1.x/api/#flask.make_response>.
    """
    # Initialize the generative model
    model = GenerativeModel(
        model_name=const.VERTEX_AI_MODEL,
        system_instruction=const.SYSTEM_INSTRUCTIONS
    )

    request_json = request.get_json(silent=True)
    request_args = request.args

    if request_json and 'query' in request_json:
        query = request_json['query']
    elif request_args and 'query' in request_args:
        query = request_args['query']
    else:
        return jsonify({"error": "No query provided."})
    
    print(query)


    # Generate prompt and get response from the model
    prompt = prompt_template.format(attributes, occasions, relations, query)
    response = model.generate_content([prompt])

    # Check if the response is empty or not
    if not response.text:
        return jsonify({"error": "Empty response from the model."})

    response_text = response.text.replace('“', '"').replace('”', '"').replace('```', '').replace('json', '').strip()

    try:
        # Parse the JSON response
        response_data = json.loads(response_text)
    except json.JSONDecodeError as e:
        return jsonify({"error": "Error decoding JSON.", "details": str(e), "response_text": response_text})

    # Extract IDs for attributes, occasions, and relations
    attribute_ids = get_ids(response_data.get("attributes", []), attributes_data, "name")
    occasion_ids = get_ids(response_data.get("occasion", []), occasions_data, "name")
    relation_ids = get_ids(response_data.get("relation", []), relations_data, "name")

    # Get the price range
    price_range = response_data.get("price_range", [])
    min_price = price_range[0] * 100 if len(price_range) > 0 and isinstance(price_range[0], int) else ""
    max_price = price_range[1] * 100 if len(price_range) > 1 and isinstance(price_range[1], int) else ""


    # Construct the API request URL with multiple occasionId and relationshipId parameters
    api_url = (
        f'https://api.toandfrom.com/v3/recommendation/testing?isApplyFilter=true'
        f'&minPrice={min_price}'
        f'&maxPrice={max_price}'
        f'&attributeIds={",".join(attribute_ids)}'
    )

    for occasion_id in occasion_ids:
        api_url += f'&occasionId={occasion_id}'
    for relation_id in relation_ids:
        api_url += f'&relationshipId={relation_id}'

    # Call the API and get the list of products
    headers = {
        'content-type': 'application/json',
        'revision': '2024-05-23'
    }
    response = requests.get(api_url, headers=headers, timeout=10)

    if response.status_code == 200:
        products = response.json()
        product_list = json.dumps(products, indent=4)
    else:
        return jsonify({"error": "API request failed.", "status_code": response.status_code, "response_text": response.text})

    # Logic to filter products
    model = GenerativeModel(
        model_name=const.VERTEX_AI_MODEL,
        system_instruction=const.PRODUCT_SYSTEM_INSTRUCTIONS
    )

    product_template = '''
    Products list:
    {0}
    
    Query: {1}
    '''

    if product_list:
        prompt = product_template.format(product_list, query)
        response = model.generate_content([prompt])

        if not response.text:
            return {"error": "Empty response from the model."}
        response_text = json.loads(response.text.replace('“', '"').replace('”', '"').replace('```', '').replace('json', '').strip())


        return {"attributes": response_data.get("attributes") ,"response": response_text}

    return {"error": "No products found."}



# curl -m 130 -X POST https://us-central1-kloudstax-429211.cloudfunctions.net/to-and-from \
# -H "Authorization: bearer $(gcloud auth print-identity-token)" \
# -H "Content-Type: application/json" \
# -d "{
#   \"query\": \"I'm looking for a birthday gift for my niece. She loves history books, arts and crafts supplies and backpacks, but she doesn't like pink colors or unicorn designs. What would be a great choice within a $40 budget?\"
# }"


# curl -m 130 -X POST https://us-central1-kloudstax-429211.cloudfunctions.net/to-and-from \
# -H "Content-Type: application/json" \
# -d "{
#   \"query\": \"I'm looking for a birthday gift for my niece. She loves history books, arts and crafts supplies and backpacks, but she doesn't like pink colors or unicorn designs. What would be a great choice within a $40 budget?\"
# }"