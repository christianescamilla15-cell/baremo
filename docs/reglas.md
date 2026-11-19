# Reglas de negocio → pruebas

La compuerta de calidad de Baremo no es el porcentaje de cobertura de código: es **una prueba por
regla**. Cada fila nombra la regla y las pruebas que la cubren como `archivo::función`. Baremo
verifica este mismo archivo sobre sí mismo con la sonda `pruebas.regla-por-prueba`: cada
referencia debe existir en el árbol y no estar marcada para saltarse.

## Puntuación (los dos números)

| Regla | Descripción | Prueba(s) |
|---|---|---|
| R01 | El cumplimiento de un check es proporcional: conformes / medibles. Corregir 58 de 59 sujetos sube la nota. | `tests/test_scoring.py::test_corregir_58_de_59_sube_la_nota_no_es_todo_o_nada`, `tests/test_scoring.py::test_cada_sujeto_corregido_mueve_la_nota` |
| R02 | `NO_MEDIBLE` no aprueba ni reprueba: sale del numerador y del denominador y baja la cobertura. | `tests/test_scoring.py::test_no_medible_no_aprueba_ni_reprueba_baja_la_cobertura`, `tests/test_scoring.py::test_marcar_como_no_medible_lo_que_cumple_nunca_sube_el_cumplimiento` |
| R03 | Degradar la instrumentación nunca produce una nota publicable mejor. | `tests/test_scoring.py::test_degradar_la_instrumentacion_no_produce_una_nota_publicable_mejor` |
| R04 | Bajo el umbral de cobertura el cumplimiento se retiene y se explica; el umbral es configurable. | `tests/test_scoring.py::test_cobertura_bajo_el_umbral_retiene_el_cumplimiento_y_lo_explica`, `tests/test_scoring.py::test_el_umbral_de_cobertura_es_configurable` |
| R05 | Lo declarado en el alcance que no se midió ni se excluyó baja la cobertura. | `tests/test_scoring.py::test_lo_declarado_que_no_se_midio_ni_se_excluyo_baja_la_cobertura` |
| R06 | Excluir con motivo declarado no castiga la cobertura; excluir sin motivo es un error de configuración. | `tests/test_scoring.py::test_excluir_con_motivo_declarado_no_castiga_la_cobertura`, `tests/test_cli_reglas.py::test_salida_3_cuando_el_excluido_no_trae_motivo` |
| R07 | Los pesos son explícitos; un check sin datos no consume su peso ni arrastra el promedio a cero. | `tests/test_scoring.py::test_una_sonda_con_peso_doble_mueve_el_doble`, `tests/test_scoring.py::test_un_check_sin_datos_no_consume_su_peso`, `tests/test_scoring.py::test_un_check_sin_datos_no_arrastra_el_promedio_a_cero` |
| R08 | Sin ningún check con dato no hay cumplimiento y la nota no es publicable. | `tests/test_scoring.py::test_todos_los_checks_sin_datos_dan_cumplimiento_none_y_no_publicable`, `tests/test_scoring.py::test_sin_checks_no_hay_nota_que_publicar` |

## Supresiones

| Regla | Descripción | Prueba(s) |
|---|---|---|
| R09 | Una supresión vigente convierte `NO_CUMPLE` en `SUPRIMIDO`: cuenta como conforme, se lista aparte y no cambia la cobertura. | `tests/test_cli_reglas.py::test_supresion_vigente_convierte_no_cumple_en_suprimido_y_se_lista`, `tests/test_scoring.py::test_suprimidos_cuentan_como_cumplimiento_pero_se_contabilizan_aparte`, `tests/test_scoring.py::test_suprimir_no_afecta_la_cobertura` |
| R10 | Una supresión vencida deja de aplicar sola y el sujeto vuelve a contar; la que vence hoy todavía aplica. | `tests/test_cli_reglas.py::test_supresion_vencida_no_aplica_y_vuelve_a_contar`, `tests/test_supresiones.py::test_supresion_que_vence_hoy_todavia_aplica` |
| R11 | Una supresión nunca tapa un `NO_MEDIBLE`. | `tests/test_cli_reglas.py::test_una_supresion_nunca_tapa_un_no_medible` |
| R12 | Una supresión exige justificación, autorizador y fecha de vencimiento; incompleta se rechaza. | `tests/test_cli_reglas.py::test_una_supresion_sin_justificacion_autor_o_vencimiento_se_rechaza` |

## Contrato de la sonda

| Regla | Descripción | Prueba(s) |
|---|---|---|
| R13 | Un `CUMPLE` o `NO_CUMPLE` sin evidencia es un error de programación; una evidencia sin fuente no es evidencia. | `tests/test_contrato.py::test_cumple_sin_evidencia_es_un_error_de_programacion`, `tests/test_contrato.py::test_no_cumple_sin_evidencia_es_un_error_de_programacion`, `tests/test_contrato.py::test_evidencia_sin_fuente_no_es_evidencia` |
| R14 | Un `NO_MEDIBLE` exige un motivo que diga qué haría falta para medir. | `tests/test_contrato.py::test_no_medible_sin_motivo_es_un_error_de_programacion` |
| R15 | Una sonda que falla es `NO_MEDIBLE` y nunca aprueba. | `tests/test_contrato.py::test_una_sonda_que_falla_es_no_medible_y_nunca_aprueba` |
| R16 | Nunca se aprueba por ausencia: un repositorio vacío no produce ningún `CUMPLE` y un sujeto ilegible es todo `NO_MEDIBLE`. | `tests/test_contrato.py::test_un_repositorio_vacio_no_aprueba_nada`, `tests/test_contrato.py::test_sujeto_ilegible_es_todo_no_medible` |
| R17 | Cada sonda registrada está documentada en el README y la versión declarada es una sola. | `tests/test_contrato.py::test_el_readme_documenta_cada_sonda_registrada`, `tests/test_contrato.py::test_la_version_declarada_es_una_sola` |

## CLI e informe

| Regla | Descripción | Prueba(s) |
|---|---|---|
| R18 | Códigos de salida: 0 publicable y sobre el mínimo, 1 bajo el mínimo, 2 no publicable (antes que 1), 3 error de operación, 64 uso incorrecto. | `tests/test_cli.py::test_salida_2_cuando_la_cobertura_no_alcanza_el_umbral`, `tests/test_cli_reglas.py::test_salida_1_cuando_el_cumplimiento_queda_bajo_el_minimo`, `tests/test_cli_reglas.py::test_salida_3_cuando_el_sujeto_no_existe`, `tests/test_cli_reglas.py::test_salida_64_ante_un_uso_incorrecto`, `tests/e2e/test_cli_e2e.py::test_evaluar_escribe_un_informe_publicable_con_todas_las_sondas`, `tests/e2e/test_cli_e2e.py::test_un_error_de_operacion_sale_con_3` |
| R19 | El informe JSON tiene un esquema estable con manifiesto, alcance, resumen, checks y supresiones. | `tests/test_cli.py::test_evaluar_produce_json_con_el_esquema_esperado` |
| R20 | El informe de consola es ASCII y, si no es publicable, dice RETENIDO y lista lo omitido. | `tests/test_cli.py::test_el_informe_de_texto_dice_retenido_y_es_ascii`, `tests/e2e/test_cli_e2e.py::test_un_alcance_sin_medir_sale_con_2_y_dice_retenido` |
| R21 | `baremo sondas` lista el catálogo completo y `baremo explicar` describe cualquier sub-check. | `tests/test_cli.py::test_sondas_lista_el_registro`, `tests/e2e/test_cli_e2e.py::test_sondas_lista_el_catalogo_completo`, `tests/e2e/test_cli_e2e.py::test_explicar_un_subcheck_nuevo` |
| R22 | El veredicto de cada sub-check de un repositorio fijo coincide con el oráculo, y el oráculo detecta un solo cambio. | `tests/test_paridad_golden.py::test_el_informe_coincide_con_el_oraculo`, `tests/test_paridad_golden.py::test_control_negativo_el_oraculo_detecta_un_solo_cambio` |

## Sondas de la 0.1.0

| Regla | Descripción | Prueba(s) |
|---|---|---|
| R23 | Los secretos se buscan por valor, no por nombre de variable, y nunca se copian al informe. | `tests/test_sondas_existentes.py::test_secretos_se_buscan_por_valor_no_por_nombre`, `tests/test_sondas_existentes.py::test_una_clave_privada_versionada_no_cumple_y_se_redacta` |
| R24 | Sin Dockerfile, el usuario de la imagen es `NO_MEDIBLE`; con `USER root` no cumple. | `tests/test_sondas_existentes.py::test_sin_dockerfile_el_usuario_de_la_imagen_es_no_medible`, `tests/test_sondas_existentes.py::test_imagen_que_corre_como_root_no_cumple_y_con_usuario_cumple` |
| R25 | Sin pipeline, los checks que dependen de él son `NO_MEDIBLE`; una acción anclada a una rama móvil no cumple. | `tests/test_sondas_existentes.py::test_sin_pipeline_los_checks_que_dependen_de_el_son_no_medibles`, `tests/test_sondas_existentes.py::test_accion_anclada_a_rama_movil_no_cumple` |
| R26 | El proceso de excepciones se reconoce en dos idiomas y nada dentro de las dependencias cuenta. | `tests/test_sondas_existentes.py::test_el_proceso_de_excepciones_se_reconoce_en_espanol`, `tests/test_sondas_existentes.py::test_una_politica_dentro_de_las_dependencias_no_cuenta` |

## Sondas de la 0.2.0

| Regla | Descripción | Prueba(s) |
|---|---|---|
| R27 | C4: cada nivel exige un diagrama real; uno con marcadores de plantilla o sin relaciones no cuenta. | `tests/test_sonda_arquitectura.py::test_c4_tres_niveles_reales_cumplen`, `tests/test_sonda_arquitectura.py::test_c4_diagrama_de_plantilla_no_cumple`, `tests/test_sonda_arquitectura.py::test_c4_diagrama_sin_relaciones_no_cuenta`, `tests/test_sonda_arquitectura.py::test_c4_barrido_truncado_es_no_medible` |
| R28 | ADR: estado, contexto, decisión y consecuencias con contenido; el título no acredita una sección. | `tests/test_sonda_arquitectura.py::test_adr_completo_cumple`, `tests/test_sonda_arquitectura.py::test_adr_sin_consecuencias_no_cumple`, `tests/test_sonda_arquitectura.py::test_adr_el_titulo_no_acredita_la_seccion_de_decision`, `tests/test_sonda_arquitectura.py::test_adr_copiado_de_la_plantilla_no_cumple` |
| R29 | README estándar: una insignia acredita sólo si su flujo existe y hace lo que dice; una sección, sólo si tiene algo verificable. | `tests/test_sonda_publicacion.py::test_readme_completo_cumple_los_siete_elementos`, `tests/test_sonda_publicacion.py::test_insignia_que_apunta_a_un_flujo_inexistente_no_cumple`, `tests/test_sonda_publicacion.py::test_seccion_que_enlaza_a_un_documento_inexistente_no_cumple`, `tests/test_sonda_publicacion.py::test_readme_ilegible_es_no_medible` |
| R30 | Licencia: texto reconocido con titular y manifiestos coherentes; texto no reconocido es `NO_MEDIBLE`. | `tests/test_sonda_publicacion.py::test_licencia_mit_con_titular_y_manifiestos_coherentes_cumple`, `tests/test_sonda_publicacion.py::test_manifiesto_con_otra_licencia_no_cumple`, `tests/test_sonda_publicacion.py::test_licencia_no_reconocida_es_no_medible` |
| R31 | Política de seguridad: canal privado, plazo y sin marcadores de plantilla. | `tests/test_sonda_publicacion.py::test_politica_con_canal_plazo_y_adaptada_cumple`, `tests/test_sonda_publicacion.py::test_politica_copiada_de_la_plantilla_no_cumple`, `tests/test_sonda_publicacion.py::test_politica_ilegible_es_no_medible` |
| R32 | API: un sub-check por operación; código con rutas y sin spec no cumple; sin API es `NO_MEDIBLE`. | `tests/test_sonda_api.py::test_un_subcheck_por_operacion_y_el_cumplimiento_es_el_porcentaje`, `tests/test_sonda_api.py::test_api_en_el_codigo_sin_especificacion_no_cumple`, `tests/test_sonda_api.py::test_repo_sin_api_es_no_medible_y_dice_por_que`, `tests/test_sonda_api.py::test_referencia_externa_hace_no_medible_la_operacion` |
| R33 | E2E: cada archivo ejerce el sistema desde fuera y afirma; recorrer sin afirmar no cumple. | `tests/test_sonda_pruebas.py::test_e2e_que_ejerce_y_afirma_cumple`, `tests/test_sonda_pruebas.py::test_e2e_que_recorre_sin_afirmar_no_cumple`, `tests/test_sonda_pruebas.py::test_e2e_ilegible_es_no_medible` |
| R34 | Golden: cada archivo de referencia lo compara una prueba; un oráculo huérfano no cumple. | `tests/test_sonda_pruebas.py::test_golden_comparado_por_una_prueba_cumple`, `tests/test_sonda_pruebas.py::test_golden_huerfano_no_cumple`, `tests/test_sonda_pruebas.py::test_sin_golden_y_barrido_truncado_es_no_medible` |
| R35 | Regla por prueba: cada referencia existe y no se salta; sin mapa de reglas es `NO_MEDIBLE`. | `tests/test_sonda_pruebas.py::test_cada_regla_es_un_sujeto_con_su_veredicto`, `tests/test_sonda_pruebas.py::test_un_modulo_saltado_entero_no_cubre_reglas`, `tests/test_sonda_pruebas.py::test_sin_mapa_de_reglas_es_no_medible` |
| R36 | Confidencialidad: la evidencia nunca incluye el término; sin lista o con una regla inválida es `NO_MEDIBLE`. | `tests/test_sonda_confidencialidad.py::test_una_mencion_no_cumple_y_la_evidencia_nunca_incluye_el_termino`, `tests/test_sonda_confidencialidad.py::test_sin_lista_es_no_medible`, `tests/test_sonda_confidencialidad.py::test_regla_invalida_es_no_medible_sin_imprimirla`, `tests/test_sonda_confidencialidad.py::test_sin_menciones_cumple_y_dice_cuanto_reviso` |
| R37 | Un escaneo cumple sólo si una verificación que puede fallar prueba que analizó algo; sin escaneos es `NO_MEDIBLE`. | `tests/test_sonda_analisis.py::test_un_subcheck_por_job_que_escanea`, `tests/test_sonda_analisis.py::test_verificacion_que_puede_no_fallar_no_cuenta`, `tests/test_sonda_analisis.py::test_sin_escaneos_es_no_medible` |
