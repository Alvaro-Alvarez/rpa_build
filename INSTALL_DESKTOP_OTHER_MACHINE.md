# Instalar En Otra Maquina

## Archivo a llevar

Copiar este instalador:

- `dist\installer\CitySensAIBuild-Installer.exe`

## Software previo obligatorio

Antes de abrir la app en la otra maquina, instalar y validar:

- Git
- Python no es necesario para el usuario final
- Advanced Installer
- Acceso a Jira
- Acceso a TFS
- Acceso a los shares de red usados por el proyecto
- Acceso a las rutas locales de repositorio que definas en la configuracion

## Instalacion

1. Ejecutar `CitySensAIBuild-Installer.exe`
2. Instalar en la ruta sugerida o en otra carpeta con permisos normales de usuario
3. Abrir `CitySensAI Build`

## Primera configuracion

La app guarda su configuracion editable del usuario en:

- `%LOCALAPPDATA%\CitySensAIBuild\config_overrides.json`

Y el layout visual del pipeline en:

- `%LOCALAPPDATA%\CitySensAIBuild\pipeline_layout.json`

Al abrir la app:

1. Ir a `Configuracion`
2. Revisar rutas como `code_path`, `assembly_paths`, `aip_paths` y shares de red
3. Ajustar tokens, ramas y parametros TFS si la maquina o el entorno cambian
4. Guardar los overrides

## Validaciones recomendadas

Antes de correr el flujo completo:

1. Probar `Validar Jira`
2. Probar un paso aislado que no haga cambios destructivos
3. Confirmar que Advanced Installer abre bien y que las imagenes de automatizacion siguen coincidiendo con la UI real

## Importante

- Si cambian resolucion, escala, idioma o apariencia de Windows/Advanced Installer, el RPA visual puede dejar de encontrar botones.
- La app no reemplaza los prerequisitos operativos del entorno. Solo empaqueta la interfaz y la logica Python.
