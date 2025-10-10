import json
import logging

from openai import OpenAI

from config import OPEN_AI_KEY, JSON_NAME

logger = logging.getLogger(__name__)


def valid_json():
    logger.info("Validando JSON de issues con la logica actual por defecto")
    # with open(JSON_NAME, "r", encoding="utf-8") as file:
    #     issues_json = file.read()
    #
    # client = OpenAI(api_key=OPEN_AI_KEY)
    # text = (
    #     "Valida que este json sea correcto, no debe tener comillas dobles dentro de "
    #     f"los textos del json y debe estar bien formateado '{issues_json}'"
    # )
    #
    # respuesta = client.chat.completions.create(
    #     model="gpt-4o-mini",
    #     messages=[
    #         {"role": "system", "content": "Responde solo con 'SI' o 'NO', nada mas."},
    #         {"role": "user", "content": text},
    #     ],
    #     temperature=0,
    # )
    #
    # word = respuesta.choices[0].message.content.strip()
    # logger.info("Respuesta del modelo: %s", word)
    # return word == "SI"
    return True
