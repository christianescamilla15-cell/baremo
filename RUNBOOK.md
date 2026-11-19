# Runbook · Baremo

Baremo **no tiene despliegue**: no hay servicio, ni nube, ni paquete publicado en un índice. Se
distribuye como código fuente desde este repositorio y se instala con `pip` desde una etiqueta de
versión. Este runbook cubre cómo se publica una versión, cómo se vuelve a la anterior y cómo se
diagnostica una corrida.

## Publicar una versión

1. Todo cambio entra por PR a `main` con los checks requeridos en verde (`ci`, `seguridad`;
   lista exacta en `.github/rulesets/main.json`). El job «Baremo se evalúa a sí mismo» falla si
   Baremo queda por debajo de su propio umbral.
2. La versión se sube en **dos** lugares que una prueba mantiene iguales: `pyproject.toml` y
   `baremo/__init__.py`. Si cambia el catálogo de sondas o la aritmética, sube la versión menor:
   las corridas de versiones distintas no se comparan.
3. Se registra el cambio en `CHANGELOG.md` y se etiqueta el commit fusionado: `git tag v0.2.0`.
4. Prueba de humo sobre la versión etiquetada, en un entorno limpio:

   ```bash
   python -m venv /tmp/humo && /tmp/humo/bin/pip install "git+https://github.com/christianescamilla15-cell/baremo@v0.2.0"
   /tmp/humo/bin/baremo --version            # baremo 0.2.0
   /tmp/humo/bin/baremo sondas | tail -1     # 16 sonda(s) registrada(s).
   /tmp/humo/bin/baremo evaluar . --formato json --salida /tmp/humo/informe.json; echo $?   # 0, 1 o 2; nunca 3
   ```

## Revertir (ensayado el 2026-11-19)

Volver a la versión anterior es instalar su etiqueta (o su commit, si aún no tiene etiqueta):

```bash
pip install --force-reinstall "git+https://github.com/christianescamilla15-cell/baremo@v0.1.0"
baremo --version     # baremo 0.1.0
baremo sondas        # 5 sonda(s) registrada(s)
```

Ensayo del 2026-11-19: se instaló `0.1.0` (commit `fabc53a`) en un entorno aparte, `baremo sondas`
listó sus 5 sondas y `baremo evaluar` sobre la rama nueva escribió el informe y salió con 0.
**Las notas de 0.1.0 y 0.2.0 no se comparan**: el catálogo pasó de 5 a 16 sondas.

## Diagnóstico

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Sale con `2` y dice «CUMPLIMIENTO RETENIDO» | La cobertura no alcanzó el umbral: demasiados `NO_MEDIBLE` u omitidos sin declarar | Leer la sección «NO MEDIBLE» del informe: cada motivo dice qué haría falta para medir |
| Sale con `3` | Configuración ilegible, sujeto inexistente o supresión incompleta | El mensaje de `stderr` nombra el archivo y el campo |
| Sale con `64` | Uso incorrecto de la línea de comandos | `baremo evaluar --help` |
| Un check aparece con el sub-check `<sonda>.ejecucion` en `NO_MEDIBLE` | La sonda lanzó una excepción (defecto de la sonda) | El motivo trae el tipo y el mensaje de la excepción; reproducir con una prueba en `tests/` |
| `seguridad.confidencialidad` en `NO_MEDIBLE` | No hay lista de términos (secreto `CONFIDENCIAL_TERMINOS` vacío o sin `~/.config/confidencial/terminos.txt`) | Configurar el secreto del repositorio; nunca versionar la lista |
| El job de secretos falla en «probar que escaneó commits» | gitleaks no escaneó la historia (clon superficial o imagen que no arrancó) | Revisar `fetch-depth: 0` y el log de `gitleaks.log` en el job |
| Semgrep falla con un hallazgo nuevo | Regla de `p/default` sobre código nuevo | Corregir; si es falso positivo, `nosemgrep` con la regla y el motivo en la línea anterior, y anotarlo en `SECURITY.md` |
