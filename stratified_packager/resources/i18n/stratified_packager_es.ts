<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="es">
<context>
  <name>Building</name>
  <message>
    <location filename="../../processing/building.py" line="241" />
    <source>Writing template layer {}/{}: {}</source>
    <translation>Escribiendo capa de plantilla {}/{}: {}</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/building.py" line="255" />
    <source>template gpkg holds %n layer(s)</source>
    <translation>
      <numerusform>el gpkg de plantilla contiene %n capa</numerusform>
      <numerusform>el gpkg de plantilla contiene %n capas</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="323" />
    <source>{} — layer {}/{}: {}</source>
    <translation>{} — capa {}/{}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="358" />
    <location filename="../../processing/building.py" line="350" />
    <source>Failed to remove partial gpkg {} after error: {}</source>
    <translation>Error al eliminar el gpkg parcial {} tras el error: {}</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="389" />
    <source>warm start used for {}</source>
    <translation>inicio en caliente usado para {}</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="606" />
    <source>spatial matching needs a stratification layer</source>
    <translation>la coincidencia espacial requiere una capa de estratificación</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="656" />
    <source>Staging {}: matching stratum {}/{}</source>
    <translation>Preparando {}: coincidencia con el estrato {}/{}</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="672" />
    <source>Staging {}: writing the staged copy</source>
    <translation>Preparando {}: escribiendo la copia preparada</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="731" />
    <source>writing table {} canceled</source>
    <translation>escritura de la tabla {} cancelada</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="734" />
    <source>writing table {} failed: {}</source>
    <translation>error al escribir la tabla {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="839" />
    <source>WAL checkpoint incomplete; not snapshotting a stale warm cache</source>
    <translation>Checkpoint WAL incompleto; no se toma una instantánea de una caché caliente obsoleta</translation>
  </message>
</context><context>
  <name>Debugging</name>
  <message>
    <location filename="../../toolbelt/debugging.py" line="103" />
    <source>debugpy is listening on %s:%s.</source>
    <translation>debugpy está escuchando en %s:%s.</translation>
  </message>
  <message>
    <location filename="../../toolbelt/debugging.py" line="109" />
    <source>Waiting for a debugger to attach...</source>
    <translation>Esperando a que se conecte un depurador...</translation>
  </message>
  <message>
    <location filename="../../toolbelt/debugging.py" line="114" />
    <source>Could not start the debugpy server.</source>
    <translation>No se pudo iniciar el servidor debugpy.</translation>
  </message>
</context><context>
  <name>InputReader</name>
  <message>
    <location filename="../../processing/params.py" line="1000" />
    <source>Cannot resolve {}: {}</source>
    <translation>No se puede resolver {}: {}</translation>
  </message>
</context><context>
  <name>LayerOptionsPageWidget</name>
  <message>
    <location filename="../../gui/wdg_layer_options_page.py" line="87" />
    <source>Could not save the layer variables.</source>
    <translation>No se pudieron guardar las variables de la capa.</translation>
  </message>
</context><context>
  <name>LayersTableDialog</name>
  <message>
    <location filename="../../gui/dlg_layers_table.py" line="172" />
    <source>Layer</source>
    <translation>Capa</translation>
  </message>
  <message>
    <location filename="../../gui/dlg_layers_table.py" line="174" />
    <source>Properties</source>
    <translation>Propiedades</translation>
  </message>
  <message>
    <location filename="../../gui/dlg_layers_table.py" line="225" />
    <source>Properties…</source>
    <translation>Propiedades…</translation>
  </message>
  <message>
    <location filename="../../gui/dlg_layers_table.py" line="319" />
    <source>Could not save the layer settings.</source>
    <translation>No se pudieron guardar las opciones de la capa.</translation>
  </message>
</context><context>
  <name>MatchingEngine</name>
  <message>
    <location filename="../../processing/matching.py" line="97" />
    <source>Operation was canceled.</source>
    <translation>La operación fue cancelada.</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="266" />
    <source>Matching cannot be resolved:
- {}</source>
    <translation>No se pudo resolver la coincidencia:
- {}</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="295" />
    <source>layer {}: invalid matching_method {}</source>
    <translation>capa {}: matching_method no válido {}</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="313" />
    <source>layer {}: no relation path to the stratification layer and no geometry on both sides; add a relation, set matching_method = whole_export, exclude the layer, or give the stratification layer geometry</source>
    <translation>capa {}: no hay ruta de relación hasta la capa de estratificación ni geometría en ambos lados; añada una relación, establezca matching_method = whole_export, excluya la capa o dele geometría a la capa de estratificación</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="338" />
    <source>layer {}: matching_method = spatial requires geometry on both the layer and the stratification layer</source>
    <translation>capa {}: matching_method = spatial requiere geometría tanto en la capa como en la capa de estratificación</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="377" />
    <source>layer {}: relation_path is not a JSON list: {}</source>
    <translation>capa {}: relation_path no es una lista JSON: {}</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="385" />
    <source>layer {}: relation_path must be a JSON list of relation ids</source>
    <translation>capa {}: relation_path debe ser una lista JSON de ids de relación</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="393" />
    <source>layer {}: invalid relation_path pin: {}</source>
    <translation>capa {}: fijación de relation_path no válida: {}</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="401" />
    <source>layer {}: matching_method = attribute but no relation path reaches the stratification layer</source>
    <translation>capa {}: matching_method = attribute, pero ninguna ruta de relación llega a la capa de estratificación</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="410" />
    <source>layer {}: multiple shortest relation paths ({}); set the layer's relation_path variable to pin one</source>
    <translation>capa {}: varias rutas de relación más cortas ({}); establezca la variable relation_path de la capa para fijar una</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="443" />
    <source>layer {}: spatial_predicate 'auto' cannot be combined with other predicates</source>
    <translation>capa {}: spatial_predicate 'auto' no se puede combinar con otros predicados</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="457" />
    <source>layer {}: invalid spatial_predicate token {!r}</source>
    <translation>capa {}: token de spatial_predicate no válido {!r}</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="575" />
    <source>relation chain layer {} is not in the project</source>
    <translation>la capa {} de la cadena de relaciones no está en el proyecto</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="605" />
    <source>relation chain produced no terminal condition</source>
    <translation>la cadena de relaciones no produjo una condición terminal</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="729" />
    <source>coordinate transform {} -&gt; {} failed for layer {}</source>
    <translation>la transformación de coordenadas {} -&gt; {} falló para la capa {}</translation>
  </message>
</context><context>
  <name>PluginOptionsPageWidget</name>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.py" line="161" />
    <source>Could not save plugin settings.</source>
    <translation>No se pudieron guardar las opciones del complemento.</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.py" line="209" />
    <source>⚠️ overridden by project variable (= {})</source>
    <translation>⚠️ reemplazado por la variable de proyecto (= {})</translation>
  </message>
</context><context>
  <name>ProjectBuilder</name>
  <message>
    <location filename="../../processing/project_builder.py" line="142" />
    <source>Failed to remove project file {}</source>
    <translation>No se pudo eliminar el archivo de proyecto {}</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="147" />
    <source>Writing the embedded project for stratum {} failed ({}): {}</source>
    <translation>error al escribir el proyecto incrustado del estrato {} ({}): {}</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="379" />
    <source>Embedded project: table {} for layer {} did not open; dropped.</source>
    <translation>Proyecto incrustado: la tabla {} para la capa {} no se abrió; descartada.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="397" />
    <source>Embedded project: payload {} for layer {} did not open; dropped.</source>
    <translation>Proyecto incrustado: el archivo de datos {} para la capa {} no se abrió; descartado.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="470" />
    <source>Embedded project: virtual layer {} source {} has no table in this stratum; dropped.</source>
    <translation>Proyecto incrustado: la capa virtual {} tiene la fuente {} sin tabla en este estrato; descartada.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="497" />
    <source>Embedded project: virtual layer {} did not re-open against the stratum gpkg; dropped.</source>
    <translation>Proyecto incrustado: la capa virtual {} no se reabrió en el gpkg del estrato; descartada.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="510" />
    <source>Embedded project: style for virtual layer {} not applied: {}</source>
    <translation>Proyecto incrustado: el estilo de la capa virtual {} no se aplicó: {}</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="565" />
    <source>Embedded project: no layer tree available.</source>
    <translation>Proyecto incrustado: no hay árbol de capas disponible.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="587" />
    <source>Embedded project: layer {} was rejected.</source>
    <translation>Proyecto incrustado: la capa {} fue rechazada.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="638" />
    <source>Embedded project: style for layer {} did not parse.</source>
    <translation>Proyecto incrustado: el estilo de la capa {} no se pudo analizar.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="646" />
    <source>Embedded project: style for layer {} not applied: {}</source>
    <translation>Proyecto incrustado: el estilo de la capa {} no se aplicó: {}</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="663" />
    <source>Embedded project: layer {}'s subset is not valid SQLite ({}), so the packaged project may show no features for it. This layer shares its table with others, so the subset is what separates them — rewrite it in SQL the GeoPackage understands. Subset: {}</source>
    <translation>Proyecto incrustado: el subconjunto de la capa {} no es SQLite válido ({}), por lo que el proyecto empaquetado puede no mostrar ninguna entidad de ella. Esta capa comparte su tabla con otras, y es el subconjunto lo que las separa — reescríbalo en SQL que el GeoPackage entienda. Subconjunto: {}</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="673" />
    <source>Embedded project: subset for layer {} was not accepted: {}</source>
    <translation>Proyecto incrustado: el subconjunto de la capa {} no se aceptó: {}</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="728" />
    <source>Embedded project: relation {} could not be remapped: {}</source>
    <translation>Proyecto incrustado: no se pudo reasignar la relación {}: {}</translation>
  </message>
</context><context>
  <name>ProjectOptionsPageWidget</name>
  <message>
    <location filename="../../gui/wdg_project_options_page.py" line="118" />
    <source>Could not save the project defaults.</source>
    <translation>No se pudieron guardar los valores predeterminados del proyecto.</translation>
  </message>
</context><context>
  <name>StrataResolution</name>
  <message>
    <location filename="../../processing/strata.py" line="187" />
    <source>STRATA_FROM_SELECTION is enabled but the stratification layer has no selected features.</source>
    <translation>STRATA_FROM_SELECTION está habilitado pero la capa de estratificación no tiene entidades seleccionadas.</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="245" />
    <source>Custom layer name expression failed to parse: {}</source>
    <translation>No se pudo analizar la expresión de nombre de capa personalizado: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="258" />
    <source>Custom layer name expression failed for layer {} in stratum {}: {}</source>
    <translation>La expresión de nombre de capa personalizado falló para la capa {} en el estrato {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="265" />
    <source>Custom layer name expression returned NULL for layer {} in stratum {}.</source>
    <translation>La expresión de nombre de capa personalizado devolvió NULL para la capa {} en el estrato {}.</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="294" />
    <source>Stratum name expression failed to parse: {}</source>
    <translation>No se pudo analizar la expresión de nombre del estrato: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="306" />
    <source>Stratum name expression failed for feature {}: {}</source>
    <translation>La expresión de nombre del estrato falló para la entidad {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="312" />
    <source>Stratum name expression returned NULL for feature {}.</source>
    <translation>La expresión de nombre del estrato devolvió NULL para la entidad {}.</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="333" />
    <source>Duplicate stratum names: {}</source>
    <translation>Nombres de estrato duplicados: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="354" />
    <source>Stratum names collide after sanitization: {}</source>
    <translation>Los nombres de estrato colisionan tras el saneamiento: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="404" />
    <source>{} path expression failed to parse: {}</source>
    <translation>No se pudo analizar la expresión de ruta de {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="419" />
    <source>{} path expression failed for stratum {}: {}</source>
    <translation>La expresión de ruta de {} falló para el estrato {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="425" />
    <source>{} path expression returned NULL for stratum {}.</source>
    <translation>La expresión de ruta de {} devolvió NULL para el estrato {}.</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="434" />
    <source>Invalid {} path for stratum {}: {}</source>
    <translation>Ruta de {} no válida para el estrato {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="501" />
    <source>Zip paths differ only by letter case (they would overwrite each other on Windows): {}</source>
    <translation>Las rutas de los zips difieren solo en mayúsculas/minúsculas (se sobrescribirían entre sí en Windows): {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="517" />
    <source>GeoPackage paths collide inside zip {}: {}</source>
    <translation>Las rutas de GeoPackage colisionan dentro del zip {}: {}</translation>
  </message>
</context><context>
  <name>StratifiedPackager</name>
  <message>
    <location filename="../../main.py" line="72" />
    <source>Plugin initialized successfully.</source>
    <translation>El complemento se inicializó correctamente.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="97" />
    <source>Help</source>
    <translation>Ayuda</translation>
  </message>
  <message>
    <location filename="../../main.py" line="107" />
    <source>Settings</source>
    <translation>Opciones</translation>
  </message>
  <message>
    <location filename="../../main.py" line="120" />
    <source>Project defaults…</source>
    <translation>Valores predeterminados del proyecto…</translation>
  </message>
  <message>
    <location filename="../../main.py" line="131" />
    <source>Configure layers for packaging…</source>
    <translation>Configurar capas para el empaquetado…</translation>
  </message>
  <message>
    <location filename="../../main.py" line="164" />
    <source>Could not find QGIS plugin help menu to add documentation link.</source>
    <translation>No se pudo encontrar el menú de ayuda de complementos de QGIS para añadir el enlace a la documentación.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="176" />
    <source>{} - Documentation</source>
    <translation>{} - Documentación</translation>
  </message>
  <message>
    <location filename="../../main.py" line="200" />
    <source>Processing provider added successfully.</source>
    <translation>Proveedor de procesos añadido correctamente.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="203" />
    <source>Failed to add processing provider.</source>
    <translation>No se pudo añadir el proveedor de procesos.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="206" />
    <source>Could not access QGIS processing registry to add provider.</source>
    <translation>No se pudo acceder al registro de procesos de QGIS para añadir el proveedor.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="217" />
    <source>Failed to tear down the plugin settings node.</source>
    <translation>No se pudo desmontar el nodo de opciones del complemento.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="227" />
    <source>Failed to tear down the plugin logging handler.</source>
    <translation>No se pudo desmontar el gestor de registro (log) del complemento.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="250" />
    <source>Failed to remove processing provider during plugin unload.</source>
    <translation>No se pudo eliminar el proveedor de procesos durante la descarga del complemento.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="252" />
    <source>Could not access QGIS processing registry to remove provider.</source>
    <translation>No se pudo acceder al registro de procesos de QGIS para eliminar el proveedor.</translation>
  </message>
</context><context>
  <name>StratifiedPackagerAlgorithm</name>
  <message>
    <location filename="../../processing/algorithm.py" line="359" />
    <source>{} does not parse: {}</source>
    <translation>{} no se puede analizar: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="388" />
    <source>This algorithm requires an open project (use --project_path).</source>
    <translation>Este algoritmo requiere un proyecto abierto (use --project_path).</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1880" />
    <location filename="../../processing/algorithm.py" line="1521" />
    <location filename="../../processing/algorithm.py" line="1373" />
    <location filename="../../processing/algorithm.py" line="1024" />
    <location filename="../../processing/algorithm.py" line="397" />
    <source>Operation was canceled.</source>
    <translation>La operación se canceló.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="486" />
    <source>OUTPUT_DIRECTORY is required.</source>
    <translation>OUTPUT_DIRECTORY es obligatorio.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="573" />
    <source>Cannot determine eligible layers: {}</source>
    <translation>No se pudieron determinar las capas aptas: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="597" />
    <source>Plugin layers cannot be packaged; excluded: {}</source>
    <translation>Las capas de complemento no se pueden empaquetar; excluidas: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="603" />
    <source>Layers riding only in the embedded project (remote/annotation/live virtual): {}</source>
    <translation>Capas presentes solo en el proyecto incrustado (remota/anotación/virtual activa): {}</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="638" />
    <source>LAYERS resolved %n entry(s) onto a layer already selected: {}. Layers sharing a data source are indistinguishable when selected by source; select them by layer id (or leave LAYERS empty) to package each one.</source>
    <translation>
      <numerusform>LAYERS resolvió %n entrada en una capa ya seleccionada: {}. Las capas que comparten un origen de datos son indistinguibles cuando se seleccionan por origen; selecciónelas por el id de capa (o deje LAYERS vacío) para empaquetar cada una.</numerusform>
      <numerusform>LAYERS resolvió %n entradas en una capa ya seleccionada: {}. Las capas que comparten un origen de datos son indistinguibles cuando se seleccionan por origen; selecciónelas por el id de capa (o deje LAYERS vacío) para empaquetar cada una.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="693" />
    <source>STRATIFICATION_LAYER is required unless EXPORT_FULL_PACKAGE is enabled (then only the full package is built).</source>
    <translation>STRATIFICATION_LAYER es obligatorio salvo que EXPORT_FULL_PACKAGE esté activado (en ese caso solo se genera el paquete completo).</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="707" />
    <source>The stratification layer yielded no strata.</source>
    <translation>La capa de estratificación no produjo ningún estrato.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="710" />
    <source>No strata to package (the stratification layer is empty).</source>
    <translation>No hay estratos para empaquetar (la capa de estratificación está vacía).</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="713" />
    <source>Resolved %n strata </source>
    <translation>
      <numerusform>Se resolvió %n estrato </numerusform>
      <numerusform>Se resolvieron %n estratos </numerusform>
    </translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="714" />
    <source>into %n zip(s).</source>
    <translation>
      <numerusform>en %n zip.</numerusform>
      <numerusform>en %n zips.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="730" />
    <source>WARM_START_DIR is required when warm start is enabled.</source>
    <translation>WARM_START_DIR es obligatorio cuando el inicio en caliente está activado.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="734" />
    <source>Warm start is enabled but no packaged layer is warm_marked — a warm run with nothing warm is always a misconfiguration.</source>
    <translation>El inicio en caliente está activado, pero ninguna capa empaquetada está marcada como warm_marked — una ejecución en caliente sin nada en caliente siempre es un error de configuración.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="759" />
    <source>Custom layer name expression for layer {} does not parse: {}</source>
    <translation>No se pudo analizar la expresión de nombre de capa personalizado para la capa {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="794" />
    <source>Invalid FULL_PACKAGE_PATH: {}</source>
    <translation>FULL_PACKAGE_PATH no válido: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="843" />
    <source>Existing outputs (OVERWRITE_MODE = error): {}</source>
    <translation>Salidas existentes (OVERWRITE_MODE = error): {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="864" />
    <source>Skipping existing output {}.zip</source>
    <translation>Omitiendo la salida existente {}.zip</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="885" />
    <source>EXTRA_DIR does not exist or is not a directory: {}</source>
    <translation>EXTRA_DIR no existe o no es un directorio: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="902" />
    <source>EXTRA_DIR entries collide with reserved zip content: {}</source>
    <translation>Las entradas de EXTRA_DIR coinciden con contenido reservado del zip: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="945" />
    <source>Removed stale build directory: {}</source>
    <translation>Se eliminó un directorio de construcción obsoleto: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="970" />
    <source>Could not fully remove the build directory: {}</source>
    <translation>No se pudo eliminar por completo el directorio de construcción: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1014" />
    <source>Duplicate layer name; table renamed to {} for layer {}</source>
    <translation>Nombre de capa duplicado; tabla renombrada a {} para la capa {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1026" />
    <source>Preparing layer {}/{}: {}</source>
    <translation>Preparando la capa {}/{}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1053" />
    <source>Layer {}: its copied source file also backs other layers ({}) — the copy drags the whole container.</source>
    <translation>Capa {}: su archivo de origen copiado también respalda otras capas ({}) — la copia arrastra todo el contenedor.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1106" />
    <source>The project has no relation manager.</source>
    <translation>El proyecto no tiene gestor de relaciones.</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="1282" />
    <source>Warm cache unusable for %n stratum(s) ({}) — staging proceeds so cold fallbacks read local copies.</source>
    <translation>
      <numerusform>Caché en caliente inutilizable para %n estrato ({}) — las copias preparadas se generan igualmente para que los repliegues en frío lean copias locales.</numerusform>
      <numerusform>Caché en caliente inutilizable para %n estratos ({}) — las copias preparadas se generan igualmente para que los repliegues en frío lean copias locales.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1306" />
    <source>layer {}: stage variable {}</source>
    <translation>capa {}: variable de preparación {}</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="1359" />
    <source>Skipping staging for %n warm-seeded group(s) — the warm cache covers every stratum.</source>
    <translation>
      <numerusform>Omitiendo la copia preparada de %n grupo sembrado en caliente — la caché en caliente cubre todos los estratos.</numerusform>
      <numerusform>Omitiendo la copia preparada de %n grupos sembrados en caliente — la caché en caliente cubre todos los estratos.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1376" />
    <source>Staging layer {}/{}: {}</source>
    <translation>Generando la copia preparada de la capa {}/{}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1585" />
    <location filename="../../processing/algorithm.py" line="1457" />
    <source>could not index staged key fields for {}: {}</source>
    <translation>no se pudieron indexar los campos clave preparados de {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1526" />
    <source>Staging relation-chain layer: {}</source>
    <translation>Generando la copia preparada de la capa de la cadena de relaciones: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1540" />
    <source>Could not stage relation-chain layer {} ({}); its hops will be queried from the project instead.</source>
    <translation>No se pudo generar la copia preparada de la capa {} de la cadena de relaciones ({}); sus saltos se consultarán en el proyecto.</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="1593" />
    <source>Staged relation-chain layer {}: %n feature(s) copied.</source>
    <translation>
      <numerusform>Capa {} de la cadena de relaciones preparada: %n entidad copiada.</numerusform>
      <numerusform>Capa {} de la cadena de relaciones preparada: %n entidades copiadas.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1609" />
    <source>Layer {} could not be cloned.</source>
    <translation>No se pudo clonar la capa {}.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1626" />
    <source>Staged copy of layer {} cannot be re-opened.</source>
    <translation>La copia preparada de la capa {} no se puede volver a abrir.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1739" />
    <source>layer {}: excluded_fields is not a JSON list: {}</source>
    <translation>capa {}: excluded_fields no es una lista JSON: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1745" />
    <source>layer {}: excluded_fields must be a JSON list of names</source>
    <translation>capa {}: excluded_fields debe ser una lista JSON de nombres</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="1877" />
    <source>Building %n strata.</source>
    <translation>
      <numerusform>Construyendo %n estrato.</numerusform>
      <numerusform>Construyendo %n estratos.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1897" />
    <source>Run finished with failures — strata: [{}]; zips: [{}]; warm caches: [{}]</source>
    <translation>La ejecución finalizó con errores — estratos: [{}]; zips: [{}]; cachés en caliente: [{}]</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="1951" />
    <source>Updating %n warm cache(s) before the deliverables.</source>
    <translation>
      <numerusform>Actualizando %n caché en caliente antes de los entregables.</numerusform>
      <numerusform>Actualizando %n cachés en caliente antes de los entregables.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1956" />
    <source>Warm cache {}/{}: {}</source>
    <translation>Caché en caliente {}/{}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1974" />
    <source>Failed to remove workdir copy of warm geopackage {}</source>
    <translation>No se pudo eliminar la copia de trabajo del geopackage en caliente {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1985" />
    <source>Stratum {}/{}: {}</source>
    <translation>Estrato {}/{}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2050" />
    <source>Stratum {}: cold fallback ({}).</source>
    <translation>Estrato {}: repliegue en frío ({}).</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2221" />
    <location filename="../../processing/algorithm.py" line="2057" />
    <source>Stratum {} failed: {}</source>
    <translation>Error en el estrato {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2089" />
    <source>warm cache not written: {}</source>
    <translation>caché en caliente no escrita: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2093" />
    <source>Stratum {}: warm cache not written ({}).</source>
    <translation>Estrato {}: caché en caliente no escrita ({}).</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2118" />
    <source>Published {}</source>
    <translation>Publicado {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2122" />
    <source>Zip {} failed: {}</source>
    <translation>Error en el zip {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2161" />
    <source>Zip {} skipped: every member stratum failed.</source>
    <translation>Zip {} omitido: todos los estratos miembros fallaron.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2170" />
    <source>Stratum {}: WAL checkpoint incomplete before zipping.</source>
    <translation>Estrato {}: checkpoint WAL incompleto antes de comprimir.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2180" />
    <source>Zipping {}.zip in the background.</source>
    <translation>Comprimiendo {}.zip en segundo plano.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2209" />
    <source>Stratum {}: writing embedded project.</source>
    <translation>Estrato {}: escribiendo el proyecto incrustado.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2219" />
    <source>Failed to remove gpkg of failed stratum {}.</source>
    <translation>No se pudo eliminar el gpkg del estrato fallido {}.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2231" />
    <source>Stratum {}: could not pre-enable WAL journaling.</source>
    <translation>Estrato {}: no se pudo preactivar el modo WAL.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2243" />
    <source>Stratum {}: embedded project not written; shipping data without it ({}).</source>
    <translation>Estrato {}: proyecto incrustado no escrito; entregando los datos sin él ({}).</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2535" />
    <source>Could not create the run report output.</source>
    <translation>No se pudo crear la salida del informe de la ejecución.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2540" />
    <source>Could not write a run report row.</source>
    <translation>No se pudo escribir una fila del informe de la ejecución.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2541" />
    <source>Run report written to {}</source>
    <translation>Informe de la ejecución escrito en {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2556" />
    <source>Package project</source>
    <translation>Empaquetar proyecto</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2561" />
    <source>Partitions the project's layers against a stratification layer and emits one zipped GeoPackage per stratum.</source>
    <translation>Particiona las capas del proyecto según una capa de estratificación y emite un GeoPackage comprimido en zip por estrato.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2574" />
    <source>&lt;p&gt;Partitions the open project's layers against a &lt;b&gt;stratification layer&lt;/b&gt; (one stratum per feature) and writes &lt;b&gt;one zipped GeoPackage per stratum&lt;/b&gt; into the output directory. Each layer's features are matched to strata either by &lt;b&gt;attribute&lt;/b&gt; (following chains of project relations) or &lt;b&gt;spatially&lt;/b&gt; (one or more predicates, including raw DE-9IM patterns, combined with OR), chosen per layer.&lt;/p&gt;&lt;h3&gt;Key parameters&lt;/h3&gt;&lt;ul&gt;&lt;li&gt;&lt;b&gt;Layers to package&lt;/b&gt; — leave empty to package every eligible layer not marked with the &lt;code&gt;stratified_packager_exclude&lt;/code&gt; variable.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Stratification layer&lt;/b&gt; and &lt;b&gt;Stratum name expression&lt;/b&gt; — the partition source and how each stratum is named (empty = feature id). Naming and path expressions can use &lt;code&gt;@stratum_name&lt;/code&gt;, &lt;code&gt;@stratum_name_sanitized&lt;/code&gt;, &lt;code&gt;@gpkg_path&lt;/code&gt; and &lt;code&gt;@gpkg_name&lt;/code&gt;.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Output directory&lt;/b&gt; — where zips are published (atomic .part rename).&lt;/li&gt;&lt;li&gt;&lt;b&gt;Existing outputs&lt;/b&gt; — overwrite, error, or skip-existing.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Embed a project per stratum&lt;/b&gt; — none, gpkg (stored inside the package), or qgz (beside it); styles, metadata, relations and auxiliary files are bundled.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Also export the full package&lt;/b&gt; — additionally emit the unpartitioned dataset as a pseudo-stratum.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Dry run&lt;/b&gt; — validate and report without writing any packages.&lt;/li&gt;&lt;/ul&gt;&lt;h3&gt;Per-layer variables&lt;/h3&gt;&lt;p&gt;Edit under &lt;i&gt;Layer Properties &amp;gt; Variables&lt;/i&gt;, the per-layer plugin page, or the plugin's &lt;i&gt;Configure layers for packaging&lt;/i&gt; dialog:&lt;/p&gt;</source>
    <translation>&lt;p&gt;Particiona las capas del proyecto abierto contra una &lt;b&gt;capa de estratificación&lt;/b&gt; (un estrato por entidad) y escribe &lt;b&gt;un GeoPackage comprimido por estrato&lt;/b&gt; en el directorio de salida. Las entidades de cada capa se asignan a los estratos por &lt;b&gt;atributo&lt;/b&gt; (siguiendo cadenas de relaciones del proyecto) o &lt;b&gt;espacialmente&lt;/b&gt; (uno o más predicados, incluidos patrones DE-9IM en bruto, combinados con OR), a elección por capa.&lt;/p&gt;&lt;h3&gt;Parámetros clave&lt;/h3&gt;&lt;ul&gt;&lt;li&gt;&lt;b&gt;Capas a empaquetar&lt;/b&gt; — dejar vacío para empaquetar todas las capas elegibles sin la variable &lt;code&gt;stratified_packager_exclude&lt;/code&gt;.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Capa de estratificación&lt;/b&gt; y &lt;b&gt;Expresión del nombre del estrato&lt;/b&gt; — la fuente de la partición y cómo se nombra cada estrato (vacío = id de la entidad). Las expresiones de nombres y rutas pueden usar &lt;code&gt;@stratum_name&lt;/code&gt;, &lt;code&gt;@stratum_name_sanitized&lt;/code&gt;, &lt;code&gt;@gpkg_path&lt;/code&gt; y &lt;code&gt;@gpkg_name&lt;/code&gt;.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Directorio de salida&lt;/b&gt; — donde se publican los zips (renombrado .part atómico).&lt;/li&gt;&lt;li&gt;&lt;b&gt;Salidas existentes&lt;/b&gt; — overwrite, error o skip-existing.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Incrustar un proyecto por estrato&lt;/b&gt; — none, gpkg (guardado dentro del paquete) o qgz (junto a él); se incluyen estilos, metadatos, relaciones y archivos auxiliares.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Exportar también el paquete completo&lt;/b&gt; — emite además el conjunto de datos sin particionar como pseudoestrato.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Simulacro&lt;/b&gt; — validar e informar sin escribir ningún paquete.&lt;/li&gt;&lt;/ul&gt;&lt;h3&gt;Variables por capa&lt;/h3&gt;&lt;p&gt;Edítelas en &lt;i&gt;Propiedades de la capa &amp;gt; Variables&lt;/i&gt;, en la página del complemento por capa o en el diálogo &lt;i&gt;Configurar capas para empaquetar&lt;/i&gt;:&lt;/p&gt;</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2605" />
    <source>&lt;h3&gt;Defaults and precedence&lt;/h3&gt;&lt;p&gt;Every omitted parameter resolves through &lt;b&gt;explicit input &amp;gt; project variable (&lt;code&gt;stratified_packager_&amp;lt;param&amp;gt;&lt;/code&gt;) &amp;gt; plugin setting &amp;gt; builtin default&lt;/b&gt;. Project- and layer-scope values are editable from the plugin's Options page, the Project Properties page and the per-layer page.&lt;/p&gt;&lt;h3&gt;Warm cache&lt;/h3&gt;&lt;p&gt;With a warm-cache directory, &lt;b&gt;Use warm start&lt;/b&gt; begins each stratum GeoPackage from a cached copy and appends only non-warm-marked layers; &lt;b&gt;Update warm cache&lt;/b&gt; first writes every stratum's cache file, then builds the deliverables seeded from that fresh cache — an interrupted run still leaves a complete, reusable cache. A cached file that no longer matches its warm-marked tables falls back to a cold build for that stratum (reported as cold-fallback).&lt;/p&gt;&lt;h3&gt;Running headless (qgis_process)&lt;/h3&gt;&lt;p&gt;Pass &lt;code&gt;--project_path&lt;/code&gt;: the algorithm requires a project. The Processing framework re-instantiates the algorithm after the project loads, so project-variable and plugin-setting defaults resolve correctly without a GUI. &lt;code&gt;QgsSettings&lt;/code&gt; is per-profile, so qgis_process uses the default profile unless overridden.&lt;/p&gt;</source>
    <translation>&lt;h3&gt;Valores predeterminados y precedencia&lt;/h3&gt;&lt;p&gt;Cada parámetro omitido se resuelve mediante &lt;b&gt;entrada explícita &amp;gt; variable de proyecto (&lt;code&gt;stratified_packager_&amp;lt;param&amp;gt;&lt;/code&gt;) &amp;gt; ajuste del complemento &amp;gt; valor predeterminado incorporado&lt;/b&gt;. Los valores de ámbito de proyecto y de capa se editan desde la página de Opciones del complemento, la página de Propiedades del proyecto y la página por capa.&lt;/p&gt;&lt;h3&gt;Caché caliente&lt;/h3&gt;&lt;p&gt;Con un directorio de caché caliente, &lt;b&gt;Usar arranque en caliente&lt;/b&gt; inicia cada GeoPackage de estrato desde una copia en caché y añade solo las capas no marcadas; &lt;b&gt;Actualizar la caché caliente&lt;/b&gt; primero escribe el archivo de caché de cada estrato y luego construye los entregables sembrados desde esa caché fresca — una ejecución interrumpida aún deja una caché completa y reutilizable. Un archivo en caché que ya no coincide con sus tablas marcadas se repliega a una construcción en frío para ese estrato (informado como cold-fallback).&lt;/p&gt;&lt;h3&gt;Ejecución sin interfaz (qgis_process)&lt;/h3&gt;&lt;p&gt;Pase &lt;code&gt;--project_path&lt;/code&gt;: el algoritmo requiere un proyecto. El framework de Processing vuelve a instanciar el algoritmo después de cargar el proyecto, de modo que los valores predeterminados de variables de proyecto y ajustes del complemento se resuelven correctamente sin GUI. &lt;code&gt;QgsSettings&lt;/code&gt; es por perfil, así que qgis_process usa el perfil predeterminado salvo que se indique otro.&lt;/p&gt;</translation>
  </message>
  <message>
    <location filename="../../processing/dedup.py" line="73" />
    <source>Layer {} is not deduplicated ({}): its subset must run on the source provider, not the GeoPackage, so it keeps its own staged copy.</source>
    <translation>La capa {} no se desduplica ({}): su subconjunto debe ejecutarse en el proveedor de origen, no en el GeoPackage, por lo que conserva su propia copia preparada.</translation>
  </message>
  <message>
    <location filename="../../processing/dedup.py" line="101" />
    <source>Deduplicating shared source into table {}: {}</source>
    <translation>Desduplicando el origen compartido en la tabla {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/dedup.py" line="119" />
    <source>Could not clear the subset of shared table {}.</source>
    <translation>No se pudo limpiar el subconjunto de la tabla compartida {}.</translation>
  </message>
  <message>
    <location filename="../../processing/dedup.py" line="158" />
    <source>Shared table {} is warm-marked through {}; every member of the dedup group follows.</source>
    <translation>La tabla compartida {} está marcada en caliente a través de {}; todos los miembros del grupo de deduplicación la siguen.</translation>
  </message>
  <message>
    <location filename="../../processing/material.py" line="232" />
    <source>layer {}: warm_marked variable {}</source>
    <translation>capa {}: variable warm_marked {}</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="153" />
    <source>(bool) — skip this layer when Layers is empty.</source>
    <translation>(bool) — omite esta capa cuando LAYERS está vacío.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="161" />
    <source>(expression) — display name for this layer in the embedded per-stratum project; evaluated per stratum and may use &lt;code&gt;@stratum_name&lt;/code&gt; / &lt;code&gt;@stratum_name_sanitized&lt;/code&gt; (empty = original name; no effect without an embedded project).</source>
    <translation>(expresión) — nombre para mostrar de esta capa en el proyecto incrustado por estrato; se evalúa por estrato y puede usar &lt;code&gt;@stratum_name&lt;/code&gt; / &lt;code&gt;@stratum_name_sanitized&lt;/code&gt; (vacío = nombre original; sin efecto si no hay proyecto incrustado).</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="173" />
    <source>— auto, attribute, spatial or whole_export.</source>
    <translation>— auto, attribute, spatial o whole_export.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="182" />
    <source>— auto, or a comma-separated list (combined with OR) of named predicates (intersects, contains, within, overlaps, crosses, touches) and 9-character DE-9IM patterns.</source>
    <translation>— auto, o una lista separada por comas (combinada con OR) de predicados con nombre (intersects, contains, within, overlaps, crosses, touches) y patrones DE-9IM de 9 caracteres.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="194" />
    <source>— JSON list of fields to drop from the exported table.</source>
    <translation>— lista JSON de campos a eliminar de la tabla exportada.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="204" />
    <source>(bool or auto) — force or forbid staging this layer's data into a local copy before the per-stratum writes; auto follows STAGE_PROVIDERS.</source>
    <translation>(bool o auto) — fuerza o impide generar la copia preparada local de los datos de esta capa antes de las escrituras por estrato; auto sigue STAGE_PROVIDERS.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="215" />
    <source>(bool) — layer belongs to the warm cache.</source>
    <translation>(bool) — la capa pertenece a la caché caliente.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="224" />
    <source>(bool) — write a virtual layer's features into each package instead of keeping the layer live (with its query) in the embedded project.</source>
    <translation>(bool) — escribe las entidades de una capa virtual en cada paquete en lugar de mantener la capa viva (con su consulta) en el proyecto incrustado.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="236" />
    <source>— JSON list of relation ids pinning an otherwise ambiguous attribute chain.</source>
    <translation>— lista JSON de ids de relaciones que fija una cadena de atributos que de otro modo sería ambigua.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="337" />
    <source>Layer Configuration</source>
    <translation>Configuración de la capa</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="342" />
    <source>Symbology</source>
    <translation>Simbología</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="347" />
    <source>3D Symbology</source>
    <translation>Simbología 3D</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="352" />
    <source>Labels</source>
    <translation>Etiquetas</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="357" />
    <source>Fields</source>
    <translation>Campos</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="362" />
    <source>Attribute Form</source>
    <translation>Formulario de atributos</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="367" />
    <source>Actions</source>
    <translation>Acciones</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="372" />
    <source>Map Tips</source>
    <translation>Consejos del mapa</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="377" />
    <source>Diagrams</source>
    <translation>Diagramas</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="382" />
    <source>Attribute Table Configuration</source>
    <translation>Configuración de la tabla de atributos</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="387" />
    <source>Rendering</source>
    <translation>Renderizado</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="392" />
    <source>Custom Properties</source>
    <translation>Propiedades personalizadas</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="397" />
    <source>Geometry Options</source>
    <translation>Opciones de geometría</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="402" />
    <source>Relations</source>
    <translation>Relaciones</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="407" />
    <source>Temporal Properties</source>
    <translation>Propiedades temporales</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="412" />
    <source>Legend Settings</source>
    <translation>Configuración de la leyenda</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="417" />
    <source>Elevation Properties</source>
    <translation>Propiedades de elevación</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="422" />
    <source>Notes</source>
    <translation>Notas</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="603" />
    <source>Layers to package (empty = all eligible layers)</source>
    <translation>Capas a empaquetar (vacío = todas las capas aptas)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="612" />
    <source>Stratification layer (one stratum per feature)</source>
    <translation>Capa de estratificación (un estrato por entidad)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="620" />
    <source>Stratum name expression (empty = feature id)</source>
    <translation>Expresión de nombre del estrato (vacío = id de la entidad)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="628" />
    <source>Only selected stratification features become strata</source>
    <translation>Solo las entidades de estratificación seleccionadas se convierten en estratos</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="637" />
    <source>GeoPackage path expression (empty = sanitized stratum name)</source>
    <translation>Expresión de ruta del GeoPackage (vacío = nombre del estrato saneado)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="647" />
    <source>Zip path expression (empty = GeoPackage name)</source>
    <translation>Expresión de ruta del zip (vacío = nombre del GeoPackage)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="656" />
    <source>Output directory</source>
    <translation>Directorio de salida</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="662" />
    <source>Zip compression level (0 = store uncompressed)</source>
    <translation>Nivel de compresión del zip (0 = almacenar sin comprimir)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="671" />
    <source>Existing outputs</source>
    <translation>Salidas existentes</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="678" />
    <source>Embed a QGIS project per stratum</source>
    <translation>Incrustar un proyecto QGIS por estrato</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="687" />
    <source>Build in a temporary folder, publish zips atomically</source>
    <translation>Construir en una carpeta temporal y publicar los zips de forma atómica</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="697" />
    <source>Include layer styles</source>
    <translation>Incluir los estilos de las capas</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="704" />
    <source>Style categories to copy (none checked = all)</source>
    <translation>Categorías de estilo a copiar (ninguna marcada = todas)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="713" />
    <source>Include layer metadata</source>
    <translation>Incluir los metadatos de las capas</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="720" />
    <source>Keep layers with no matching features as empty tables</source>
    <translation>Mantener las capas sin entidades coincidentes como tablas vacías</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="730" />
    <source>Write layers sharing a data source as one table</source>
    <translation>Escribir las capas que comparten un origen de datos como una sola tabla</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="739" />
    <source>Stage every layer of these data providers (see the stage layer variable)</source>
    <translation>Generar copia preparada de todas las capas de estos proveedores de datos (ver la variable de capa stage)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="749" />
    <source>Also export the full (unpartitioned) package</source>
    <translation>Exportar también el paquete completo (sin particionar)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="758" />
    <source>Full package path (empty = &lt;project name&gt;_full)</source>
    <translation>Ruta del paquete completo (vacío = &lt;nombre del proyecto&gt;_full)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="766" />
    <source>Write a report.csv into each published zip</source>
    <translation>Escribir un report.csv en cada zip publicado</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="775" />
    <source>Extra files directory (copied into every zip root)</source>
    <translation>Directorio de archivos adicionales (copiado en la raíz de cada zip)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="783" />
    <source>Warm cache directory</source>
    <translation>Directorio de la caché en caliente</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="789" />
    <source>Warm cache mode</source>
    <translation>Modo de la caché en caliente</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="796" />
    <source>Write a .sha256 file next to each zip</source>
    <translation>Escribir un archivo .sha256 junto a cada zip</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="805" />
    <source>Dry run (validate and report only, write no packages)</source>
    <translation>Simulación (solo validar e informar, sin escribir paquetes)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="1283" />
    <source>Run report (loaded as a memory layer when no path is given)</source>
    <translation>Informe de la ejecución (cargado como capa en memoria cuando no se indica una ruta)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="1402" />
    <source>Published zip paths (JSON array)</source>
    <translation>Rutas de los zips publicados (arreglo JSON)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="1408" />
    <source>Strata resolved</source>
    <translation>Estratos resueltos</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="1411" />
    <source>Zips published</source>
    <translation>Zips publicados</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="1415" />
    <source>Failed strata (JSON array)</source>
    <translation>Estratos con errores (arreglo JSON)</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/reporting.py" line="211" />
    <source>Layer {}: %n feature(s) match no stratum.</source>
    <translation>
      <numerusform>Capa {}: %n entidad no coincide con ningún estrato.</numerusform>
      <numerusform>Capa {}: %n entidades no coinciden con ningún estrato.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/virtual.py" line="106" />
    <source>Virtual layer {} is materialized but queries non-local source(s) ({}). Its query re-runs against them for every stratum, which on a database provider means many round-trips and may exhaust the provider's connection pool. Consider pushing the join into the source — a subset filter, a view, or a materialized view — and packaging that layer instead.</source>
    <translation>La capa virtual {} se materializa pero consulta fuentes no locales ({}). Su consulta se vuelve a ejecutar contra ellas en cada estrato, lo que en un proveedor de base de datos supone muchas idas y vueltas y puede agotar el grupo de conexiones del proveedor. Considere trasladar la unión a la fuente — un filtro de subconjunto, una vista o una vista materializada — y empaquetar esa capa en su lugar.</translation>
  </message>
  <message>
    <location filename="../../processing/virtual.py" line="148" />
    <source>layer {}: materialize_virtual_layer {} is not a boolean: {}</source>
    <translation>capa {}: materialize_virtual_layer {} no es un booleano: {}</translation>
  </message>
  <message>
    <location filename="../../processing/virtual.py" line="165" />
    <source>Virtual layer {} references sources not packaged ({}); materializing it instead of keeping it live in the embedded project.</source>
    <translation>La capa virtual {} referencia fuentes no empaquetadas ({}); se materializará en lugar de mantenerla activa en el proyecto incrustado.</translation>
  </message>
</context><context>
  <name>StratifiedPackagerProvider</name>
  <message>
    <location filename="../../processing/provider.py" line="57" />
    <source>Failed to register the %s algorithm.</source>
    <translation>No se pudo registrar el algoritmo %s.</translation>
  </message>
  <message>
    <location filename="../../processing/provider.py" line="76" />
    <source>No project available; default-refresh signals not connected.</source>
    <translation>No hay ningún proyecto disponible; las señales de actualización de valores predeterminados no se conectaron.</translation>
  </message>
</context><context>
  <name>StratifiedPackagerWidgets</name>
  <message>
    <location filename="../../gui/widgets.py" line="82" />
    <source>Overwrite</source>
    <translation>Sobrescribir</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="85" />
    <source>Error if exists</source>
    <translation>Error si existe</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="88" />
    <source>Skip existing</source>
    <translation>Omitir existentes</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="95" />
    <source>None</source>
    <translation>Ninguno</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="96" />
    <source>Embedded in GeoPackage</source>
    <translation>Incrustado en el GeoPackage</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="99" />
    <source>Standalone .qgz project</source>
    <translation>Proyecto .qgz independiente</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="106" />
    <source>Off</source>
    <translation>Desactivado</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="107" />
    <source>Start from warm cache</source>
    <translation>Iniciar desde la caché en caliente</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="110" />
    <source>Refresh warm cache</source>
    <translation>Actualizar la caché en caliente</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="117" />
    <source>By attribute (relations)</source>
    <translation>Por atributo (relaciones)</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="120" />
    <source>Spatial</source>
    <translation>Espacial</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="123" />
    <source>Whole export</source>
    <translation>Exportación completa</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="140" />
    <source>inherit (= {})</source>
    <translation>heredar (= {})</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="142" />
    <source>inherit</source>
    <translation>heredar</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="417" />
    <source>all</source>
    <translation>todas</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="515" />
    <source>DE-9IM pattern(s)…</source>
    <translation>Patrón(es) DE-9IM…</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="522" />
    <source>DE-9IM:</source>
    <translation>DE-9IM:</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="614" />
    <source>Invalid DE-9IM pattern(s): {}</source>
    <translation>Patrón(es) DE-9IM no válido(s): {}</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="804" />
    <source>not set</source>
    <translation>sin definir</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="891" />
    <source>Enabled</source>
    <translation>Activado</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="892" />
    <source>Disabled</source>
    <translation>Desactivado</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="1300" />
    <source>auto</source>
    <translation>auto</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="1311" />
    <source>keep original</source>
    <translation>mantener original</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="152" />
    <source>Exclude layer</source>
    <translation>Excluir capa</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="160" />
    <source>Custom layer name (expression)</source>
    <translation>Nombre de capa personalizado (expresión)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="172" />
    <source>Matching method</source>
    <translation>Método de coincidencia</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="181" />
    <source>Spatial predicate(s)</source>
    <translation>Predicado(s) espacial(es)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="193" />
    <source>Excluded fields</source>
    <translation>Campos excluidos</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="203" />
    <source>Stage layer data</source>
    <translation>Preparar datos de capa</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="214" />
    <source>Warm-marked</source>
    <translation>Marcado como en caliente</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="223" />
    <source>Materialize virtual layer</source>
    <translation>Materializar capa virtual</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="235" />
    <source>Relation path (JSON ids)</source>
    <translation>Ruta de relación (ids JSON)</translation>
  </message>
</context><context>
  <name>dlg_stratified_packager_layers_table</name>
  <message>
    <location filename="../../gui/dlg_layers_table.ui" line="0" />
    <source>Stratified Packager - Configure layers</source>
    <translation>Stratified Packager - Configurar capas</translation>
  </message>
  <message>
    <location filename="../../gui/dlg_layers_table.ui" line="0" />
    <source>Per-layer packaging settings. An empty cell inherits the builtin default; matching columns apply to vector layers only.</source>
    <translation>Opciones de empaquetado por capa. Una celda vacía hereda el valor predeterminado interno; las columnas de coincidencia se aplican solo a las capas vectoriales.</translation>
  </message>
  <message>
    <location filename="../../gui/dlg_layers_table.ui" line="0" />
    <source>Plugin settings…</source>
    <translation>Opciones del complemento…</translation>
  </message>
  <message>
    <location filename="../../gui/dlg_layers_table.ui" line="0" />
    <source>Project defaults…</source>
    <translation>Valores predeterminados del proyecto…</translation>
  </message>
</context><context>
  <name>wdg_stratified_packager_layer_options_page</name>
  <message>
    <location filename="../../gui/wdg_layer_options_page.ui" line="0" />
    <source>Stratified Packager</source>
    <translation>Stratified Packager</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_layer_options_page.ui" line="0" />
    <source>How this layer participates in Stratified Packager runs. An empty field inherits the builtin default (shown as the placeholder).</source>
    <translation>Cómo participa esta capa en las ejecuciones de Stratified Packager. Un campo vacío hereda el valor predeterminado interno (mostrado como marcador de posición).</translation>
  </message>
</context><context>
  <name>wdg_stratified_packager_plugin_options_page</name>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Stratified Packager - Settings</source>
    <translation>Stratified Packager - Opciones</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Algorithm defaults</source>
    <translation>Valores predeterminados del algoritmo</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Plugin-wide defaults for the Package project algorithm. A project variable, where set, overrides the value here for that project.</source>
    <translation>Valores predeterminados de todo el complemento para el algoritmo Empaquetar proyecto. Una variable de proyecto, cuando se define, reemplaza el valor de aquí para ese proyecto.</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Miscellaneous</source>
    <translation>Varios</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Report an issue</source>
    <translation>Informar de un problema</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Version used to save settings:</source>
    <translation>Versión usada para guardar las opciones:</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Help</source>
    <translation>Ayuda</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Reset settings to factory defaults</source>
    <translation>Restablecer las opciones a los valores de fábrica</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Enable debug mode.</source>
    <translation>Activar el modo de depuración.</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Debug mode (degraded performances)</source>
    <translation>Modo de depuración (rendimiento reducido)</translation>
  </message>
</context><context>
  <name>wdg_stratified_packager_project_options_page</name>
  <message>
    <location filename="../../gui/wdg_project_options_page.ui" line="0" />
    <source>Stratified Packager</source>
    <translation>Stratified Packager</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_project_options_page.ui" line="0" />
    <source>Project-scoped defaults for Stratified Packager. An empty field inherits the plugin setting (shown as the placeholder); clearing a field falls back to that default.</source>
    <translation>Valores predeterminados con ámbito de proyecto para Stratified Packager. Un campo vacío hereda la opción del complemento (mostrada como marcador de posición); al borrar un campo se vuelve a ese valor predeterminado.</translation>
  </message>
</context></TS>
