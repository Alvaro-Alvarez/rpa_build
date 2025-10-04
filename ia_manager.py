import json
from openai import OpenAI
from config import OPEN_AI_KEY, JSON_NAME

def valid_json():
    # with open(JSON_NAME, "r", encoding="utf-8") as file:
    #     issues_json = file.read()
    
    # client = OpenAI(api_key=OPEN_AI_KEY)
    # text = f"Valida que este json sea correcto, no debe tener comillas dobles dentro de los textos del json y debe estar bien formateado '{issues_json}'"

    # # Llamada al modelo para responder con una sola palabra
    # respuesta = client.chat.completions.create(
    #     model="gpt-4o-mini",
    #     messages=[
    #         {"role": "system", "content": "Responde solo con 'SI' o 'NO', nada más."},
    #         {"role": "user", "content": text}
    #     ],
    #     temperature=0
    # )

    # word = respuesta.choices[0].message.content.strip()
    # print("Respuesta del modelo:", word)

    # return word == "SI"
    return True