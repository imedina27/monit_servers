<#
.SINOPSIS
    Crea (o recrea) la tarea programada de Windows que corre la ingesta
    de Monit_Servers_V2 al iniciar sesion.

.DESCRIPCION
    Busca el virtualenv de pipenv del proyecto automaticamente (no hace
    falta editar rutas a mano) y registra la tarea "MonitServersV2_Ingesta"
    con disparador "al iniciar sesion". Si la tarea ya existe, la
    reemplaza (es seguro volver a correr este script).

.NOTAS
    Requiere PowerShell como Administrador (registrar tareas programadas
    esta restringido en esta maquina para usuarios sin elevar).
#>

$ErrorActionPreference = "Stop"

$proyecto = Split-Path -Parent $PSScriptRoot
$nombreTarea = "MonitServersV2_Ingesta"

# Ubica el virtualenv de pipenv por convencion de nombre (<carpeta>-<hash>),
# sin depender de llamar a 'pipenv' (evita variables de entorno heredadas
# que puedan apuntar al venv de otro proyecto).
$workonHome = if ($env:WORKON_HOME) { $env:WORKON_HOME } else { Join-Path $env:USERPROFILE ".virtualenvs" }
$nombreProyecto = Split-Path -Leaf $proyecto
$venvDir = Get-ChildItem -Path $workonHome -Directory -Filter "$nombreProyecto-*" -ErrorAction SilentlyContinue | Select-Object -First 1

if (-not $venvDir) {
    throw "No se encontro el virtualenv de '$nombreProyecto' en $workonHome. Corre 'pipenv install' en la carpeta del proyecto primero."
}

$python = Join-Path $venvDir.FullName "Scripts\python.exe"
Write-Host "Python detectado: $python"
Write-Host "Proyecto: $proyecto"

if (Get-ScheduledTask -TaskName $nombreTarea -ErrorAction SilentlyContinue) {
    Write-Host "La tarea '$nombreTarea' ya existe, se reemplaza..."
    Unregister-ScheduledTask -TaskName $nombreTarea -Confirm:$false
}

$accion = New-ScheduledTaskAction -Execute $python -Argument "ingesta\ingesta.py" -WorkingDirectory $proyecto
$disparador = New-ScheduledTaskTrigger -AtLogOn

Register-ScheduledTask -TaskName $nombreTarea `
    -Action $accion `
    -Trigger $disparador `
    -Description "Corre la ingesta de Monit_Servers_V2 (descarga/carga de lecturas) al iniciar sesion" `
    -User "$env:USERDOMAIN\$env:USERNAME" | Out-Null

Write-Host "`nTarea creada:"
Get-ScheduledTask -TaskName $nombreTarea | Select-Object TaskName, State
