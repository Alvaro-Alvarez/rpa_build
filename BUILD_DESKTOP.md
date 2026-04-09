# Build Desktop

## Objetivo

Generar el ejecutable desktop de `CitySensAI Build` y, si hay Inno Setup instalado, tambien el instalador de Windows.

## Requisitos

- Windows
- `.venv` creado
- Dependencias del proyecto instaladas
- `PyInstaller` instalado o con acceso a internet para que el script lo instale
- Opcional: Inno Setup 6 para generar el instalador `.exe`

## Ejecutar

```powershell
.\build_desktop_installer.ps1
```

## Resultado

Si solo esta disponible PyInstaller:

- `dist\CitySensAIBuild\CitySensAIBuild.exe`

Si tambien esta instalado Inno Setup:

- `dist\installer\CitySensAIBuild-Installer.exe`

## Notas

- El build incluye `assets\images`, necesarios para la automatizacion visual.
- El layout manual del pipeline se guarda en `pipeline_layout.json`.
- Los overrides de configuracion se guardan en `config_overrides.json`.
- El instalador no configura rutas externas, accesos a red ni software como Advanced Installer. Eso sigue siendo prerrequisito de la maquina destino.
