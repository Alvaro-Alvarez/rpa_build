# Setup En Otra Maquina

Este proyecto esta pensado para ejecutarse en Windows y depende de software local, repositorios externos, shares de red y automatizacion de UI.

## 1. Requisitos del sistema

- Windows 10 o Windows 11
- PowerShell disponible
- Acceso a red a:
  - Jira: `https://jiraneclatam.atlassian.net`
  - TFS: `http://rcoc-servicios:8080/tfs`
  - Shares:
    - `\\172.20.80.29\CitySensAI PaqDeDespliegue\CitySensAI\DevNewVersionAR\CCS`
    - `\\172.20.80.29\CitySensAI PaqDeDespliegue\CitySensAI\DevNewVersionAR\CCSI`
- Permisos para clonar/usar los repositorios de codigo en `C:\NEC-GIT\...`
- Resolucion de pantalla compatible con las capturas usadas por `pyautogui`

## 2. Software a instalar

- Python 3.10 o superior
  - El proyecto usa `match/case` en `main.py`, asi que Python 3.9 o menor no sirve.
- Git for Windows
- Microsoft Teams
- Advanced Installer
- Excel no es obligatorio para generar el `.xlsx`, pero puede ser util para revisar salidas

## 3. Repositorios externos que deben existir localmente

Segun `config.py`, estas rutas deben existir:

- `C:\NEC-GIT\C2ISMain_GIT`
- `C:\NEC-GIT\CCSCommon_GIT`
- `C:\NEC-GIT\CCSI_GIT`

Si alguna ruta cambia, hay que actualizarla en `config.py`.

## 4. Crear entorno Python

Desde la raiz del proyecto:

```powershell
.\bootstrap.ps1
```

Eso crea `.venv`, actualiza `pip`, instala dependencias desde `requirements.txt` y corre una validacion basica.

Si prefieres hacerlo manualmente:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 5. Librerias Python a instalar

El archivo `requirements.txt` ya deja preparadas las dependencias inferidas del codigo actual:

```powershell
pip install -r requirements.txt
```

Notas:

- `pandas` se usa para exportar Excel.
- `openpyxl` es necesario para `DataFrame.to_excel(...)`.
- `requests` se usa para Jira y TFS.
- `openai` esta importado en `managers/ia_manager.py`.
- `pyautogui`, `pillow` y `opencv-python` se usan para reconocimiento visual y automatizacion.
- `pygetwindow` se usa para manipular la ventana de Advanced Installer.
- `pyperclip` mejora el pegado en Teams; si falta, el codigo tiene fallback a tipeo.

## 6. Configuracion que hay que revisar

El archivo `config.py` concentra casi toda la configuracion operativa:

- Versiones:
  - `BUILD_VERSION`
  - `PREVIOUS_BUILD_VERSION`
  - `CURRENT_VERSION_CCSI`
  - `NEXT_VERSION_CCSI`
- Rama principal:
  - `MAIN_BRANCH`
- Credenciales y queries:
  - `JIRA_USER`
  - `JIRA_TOKEN`
  - `JIRA_JQL`
  - `JIRA_VALIDATE_TAGS`
  - `OPEN_AI_KEY`
  - `CODES.*.tfs.PAT`
- Rutas locales:
  - `CODES.*.code_path`
  - `assembly_paths`
  - `aip_paths`
  - `change_log_path`
- Shares de salida:
  - `BUILDS_PACKAGE_DIRECTORY`
  - `BUILD_CCSI_DIRECTORY`
- Participantes e imagenes de Teams:
  - `TEAMS_CONFIRMATION_PARTICIPANTS`
- Targets visuales del RPA:
  - `RPA_UI_TARGETS`

## 7. Capturas e imagenes necesarias

La automatizacion depende de las imagenes en:

- `assets/images`

Esas capturas deben seguir coincidiendo con:

- El chat de Teams
- La barra de tareas
- La interfaz de Advanced Installer
- Los mensajes de confirmacion usados en Teams

Si cambia el tema visual, zoom, resolucion, idioma o version de Teams/Advanced Installer, probablemente haya que volver a capturar imagenes.

## 8. Riesgos importantes antes de ejecutar

- `managers/git_manager.py` usa `git reset --hard` y `git clean -fd` en algunos flujos.
- Eso puede borrar cambios locales en los repositorios externos.
- No conviene ejecutar el proyecto en una maquina donde esos repos tengan trabajo sin respaldar.

## 9. Validacion minima recomendada

Con el entorno creado, correr:

```powershell
python _check_syntax.py
```

Y como verificacion general:

```powershell
@'
import py_compile
files = [
    'main.py',
    'config.py',
    'logging_config.py',
    'enums/enums.py',
    'managers/file_manager.py',
    'managers/git_manager.py',
    'managers/ia_manager.py',
    'managers/jira_manager.py',
    'managers/rpa_manager.py',
    'managers/teams_manager.py',
    'managers/tfs_manager.py',
]
for f in files:
    py_compile.compile(f, doraise=True)
    print(f'OK: {f}')
'@ | python -
```

## 10. Primera ejecucion

Ejecutar todas las acciones:

```powershell
python main.py all
```

O una accion puntual:

```powershell
python main.py get_jira_issues
python main.py update_change_log
python main.py update_assembly_versions
python main.py update_aip_versions
python main.py upload_code_and_pr
python main.py build_package
```

## 11. Recomendacion tecnica

Antes de moverlo a otra maquina de forma estable, convendria hacer estas mejoras:

- Sacar secretos de `config.py` y moverlos a variables de entorno o un archivo local no versionado.
- Mantener actualizado `requirements.txt` cuando entren nuevas librerias.
- Extender `bootstrap.ps1` si luego quieres validar accesos, shares o repos externos.
- Agregar pruebas basicas para managers no UI.
- Separar configuracion por entorno/maquina.
