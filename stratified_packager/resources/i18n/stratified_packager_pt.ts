<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="pt_BR">
<context>
  <name>Building</name>
  <message>
    <location filename="../../processing/building.py" line="240" />
    <source>Writing template layer {}/{}: {}</source>
    <translation>Gravando camada de modelo {}/{}: {}</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/building.py" line="255" />
    <source>template gpkg holds %n layer(s)</source>
    <translation>
      <numerusform>o gpkg de modelo contém %n camada</numerusform>
      <numerusform>o gpkg de modelo contém %n camadas</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="323" />
    <source>{} — layer {}/{}: {}</source>
    <translation>{} — camada {}/{}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="358" />
    <location filename="../../processing/building.py" line="350" />
    <source>Failed to remove partial gpkg {} after error: {}</source>
    <translation>Falha ao remover o gpkg parcial {} após o erro: {}</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="389" />
    <source>warm start used for {}</source>
    <translation>início a quente usado para {}</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="606" />
    <source>spatial matching needs a stratification layer</source>
    <translation>a correspondência espacial requer uma camada de estratificação</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="656" />
    <source>Staging {}: matching stratum {}/{}</source>
    <translation>Preparando {}: correspondência com o estrato {}/{}</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="672" />
    <source>Staging {}: writing the staged copy</source>
    <translation>Preparando {}: gravando a cópia preparada</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="731" />
    <source>writing table {} canceled</source>
    <translation>gravação da tabela {} cancelada</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="734" />
    <source>writing table {} failed: {}</source>
    <translation>falha ao gravar a tabela {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/building.py" line="839" />
    <source>WAL checkpoint incomplete; not snapshotting a stale warm cache</source>
    <translation>Checkpoint WAL incompleto; não será feito snapshot de um cache quente obsoleto</translation>
  </message>
</context><context>
  <name>Debugging</name>
  <message>
    <location filename="../../toolbelt/debugging.py" line="103" />
    <source>debugpy is listening on %s:%s.</source>
    <translation>debugpy está escutando em %s:%s.</translation>
  </message>
  <message>
    <location filename="../../toolbelt/debugging.py" line="109" />
    <source>Waiting for a debugger to attach...</source>
    <translation>Aguardando a conexão de um depurador...</translation>
  </message>
  <message>
    <location filename="../../toolbelt/debugging.py" line="114" />
    <source>Could not start the debugpy server.</source>
    <translation>Não foi possível iniciar o servidor debugpy.</translation>
  </message>
</context><context>
  <name>InputReader</name>
  <message>
    <location filename="../../processing/params.py" line="985" />
    <source>Cannot resolve {}: {}</source>
    <translation>Não foi possível resolver {}: {}</translation>
  </message>
</context><context>
  <name>LayerOptionsPageWidget</name>
  <message>
    <location filename="../../gui/wdg_layer_options_page.py" line="87" />
    <source>Could not save the layer variables.</source>
    <translation>Não foi possível salvar as variáveis da camada.</translation>
  </message>
</context><context>
  <name>LayersTableDialog</name>
  <message>
    <location filename="../../gui/dlg_layers_table.py" line="172" />
    <source>Layer</source>
    <translation>Camada</translation>
  </message>
  <message>
    <location filename="../../gui/dlg_layers_table.py" line="174" />
    <source>Properties</source>
    <translation>Propriedades</translation>
  </message>
  <message>
    <location filename="../../gui/dlg_layers_table.py" line="225" />
    <source>Properties…</source>
    <translation>Propriedades…</translation>
  </message>
  <message>
    <location filename="../../gui/dlg_layers_table.py" line="319" />
    <source>Could not save the layer settings.</source>
    <translation>Não foi possível salvar as configurações da camada.</translation>
  </message>
</context><context>
  <name>MatchingEngine</name>
  <message>
    <location filename="../../processing/matching.py" line="97" />
    <source>Operation was canceled.</source>
    <translation>A operação foi cancelada.</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="258" />
    <source>Matching cannot be resolved:
- {}</source>
    <translation>A correspondência não pôde ser resolvida:
- {}</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="287" />
    <source>layer {}: invalid matching_method {}</source>
    <translation>camada {}: matching_method inválido {}</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="305" />
    <source>layer {}: no relation path to the stratification layer and no geometry on both sides; add a relation, set matching_method = whole_export, exclude the layer, or give the stratification layer geometry</source>
    <translation>camada {}: não há caminho de relação até a camada de estratificação nem geometria em ambos os lados; adicione uma relação, defina matching_method = whole_export, exclua a camada ou forneça geometria à camada de estratificação</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="330" />
    <source>layer {}: matching_method = spatial requires geometry on both the layer and the stratification layer</source>
    <translation>camada {}: matching_method = spatial requer geometria tanto na camada quanto na camada de estratificação</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="369" />
    <source>layer {}: relation_path is not a JSON list: {}</source>
    <translation>camada {}: relation_path não é uma lista JSON: {}</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="377" />
    <source>layer {}: relation_path must be a JSON list of relation ids</source>
    <translation>camada {}: relation_path deve ser uma lista JSON de ids de relação</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="385" />
    <source>layer {}: invalid relation_path pin: {}</source>
    <translation>camada {}: fixação de relation_path inválida: {}</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="393" />
    <source>layer {}: matching_method = attribute but no relation path reaches the stratification layer</source>
    <translation>camada {}: matching_method = attribute, mas nenhum caminho de relação alcança a camada de estratificação</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="402" />
    <source>layer {}: multiple shortest relation paths ({}); set the layer's relation_path variable to pin one</source>
    <translation>camada {}: vários caminhos de relação mais curtos ({}); defina a variável relation_path da camada para fixar um</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="435" />
    <source>layer {}: spatial_predicate 'auto' cannot be combined with other predicates</source>
    <translation>camada {}: spatial_predicate 'auto' não pode ser combinado com outros predicados</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="449" />
    <source>layer {}: invalid spatial_predicate token {!r}</source>
    <translation>camada {}: token de spatial_predicate inválido {!r}</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="573" />
    <source>relation chain layer {} is not in the project</source>
    <translation>a camada {} da cadeia de relações não está no projeto</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="594" />
    <source>relation chain produced no terminal condition</source>
    <translation>a cadeia de relações não produziu uma condição terminal</translation>
  </message>
  <message>
    <location filename="../../processing/matching.py" line="718" />
    <source>coordinate transform {} -&gt; {} failed for layer {}</source>
    <translation>a transformação de coordenadas {} -&gt; {} falhou para a camada {}</translation>
  </message>
</context><context>
  <name>PluginOptionsPageWidget</name>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.py" line="161" />
    <source>Could not save plugin settings.</source>
    <translation>Não foi possível salvar as configurações do complemento.</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.py" line="209" />
    <source>⚠️ overridden by project variable (= {})</source>
    <translation>⚠️ sobrescrito pela variável de projeto (= {})</translation>
  </message>
</context><context>
  <name>ProjectBuilder</name>
  <message>
    <location filename="../../processing/project_builder.py" line="125" />
    <source>Failed to remove project file {}</source>
    <translation>Falha ao remover o arquivo de projeto {}</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="130" />
    <source>Writing the embedded project for stratum {} failed ({}): {}</source>
    <translation>falha ao gravar o projeto incorporado do estrato {} ({}): {}</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="233" />
    <source>Embedded project: table {} for layer {} did not open; dropped.</source>
    <translation>Projeto incorporado: a tabela {} para a camada {} não abriu; descartada.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="251" />
    <source>Embedded project: payload {} for layer {} did not open; dropped.</source>
    <translation>Projeto incorporado: o arquivo de dados {} para a camada {} não abriu; descartado.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="324" />
    <source>Embedded project: virtual layer {} source {} has no table in this stratum; dropped.</source>
    <translation>Projeto incorporado: a camada virtual {} tem a fonte {} sem tabela neste estrato; descartada.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="351" />
    <source>Embedded project: virtual layer {} did not re-open against the stratum gpkg; dropped.</source>
    <translation>Projeto incorporado: a camada virtual {} não reabriu no gpkg do estrato; descartada.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="364" />
    <source>Embedded project: style for virtual layer {} not applied: {}</source>
    <translation>Projeto incorporado: o estilo da camada virtual {} não foi aplicado: {}</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="419" />
    <source>Embedded project: no layer tree available.</source>
    <translation>Projeto incorporado: nenhuma árvore de camadas disponível.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="441" />
    <source>Embedded project: layer {} was rejected.</source>
    <translation>Projeto incorporado: a camada {} foi rejeitada.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="492" />
    <source>Embedded project: style for layer {} did not parse.</source>
    <translation>Projeto incorporado: o estilo da camada {} não pôde ser analisado.</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="500" />
    <source>Embedded project: style for layer {} not applied: {}</source>
    <translation>Projeto incorporado: o estilo da camada {} não foi aplicado: {}</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="512" />
    <source>Embedded project: subset for layer {} was not accepted: {}</source>
    <translation>Projeto incorporado: o subconjunto da camada {} não foi aceito: {}</translation>
  </message>
  <message>
    <location filename="../../processing/project_builder.py" line="567" />
    <source>Embedded project: relation {} could not be remapped: {}</source>
    <translation>Projeto incorporado: não foi possível remapear a relação {}: {}</translation>
  </message>
</context><context>
  <name>ProjectOptionsPageWidget</name>
  <message>
    <location filename="../../gui/wdg_project_options_page.py" line="118" />
    <source>Could not save the project defaults.</source>
    <translation>Não foi possível salvar os padrões do projeto.</translation>
  </message>
</context><context>
  <name>StrataResolution</name>
  <message>
    <location filename="../../processing/strata.py" line="186" />
    <source>STRATA_FROM_SELECTION is enabled but the stratification layer has no selected features.</source>
    <translation>STRATA_FROM_SELECTION está habilitado, mas a camada de estratificação não tem feições selecionadas.</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="242" />
    <source>Custom layer name expression failed to parse: {}</source>
    <translation>A expressão de nome de camada personalizado não pôde ser analisada: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="255" />
    <source>Custom layer name expression failed for layer {} in stratum {}: {}</source>
    <translation>A expressão de nome de camada personalizado falhou para a camada {} no estrato {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="262" />
    <source>Custom layer name expression returned NULL for layer {} in stratum {}.</source>
    <translation>A expressão de nome de camada personalizado retornou NULL para a camada {} no estrato {}.</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="291" />
    <source>Stratum name expression failed to parse: {}</source>
    <translation>A expressão de nome do estrato não pôde ser analisada: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="303" />
    <source>Stratum name expression failed for feature {}: {}</source>
    <translation>A expressão de nome do estrato falhou para a feição {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="309" />
    <source>Stratum name expression returned NULL for feature {}.</source>
    <translation>A expressão de nome do estrato retornou NULL para a feição {}.</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="330" />
    <source>Duplicate stratum names: {}</source>
    <translation>Nomes de estrato duplicados: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="351" />
    <source>Stratum names collide after sanitization: {}</source>
    <translation>Os nomes de estrato colidem após a higienização: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="399" />
    <source>{} path expression failed to parse: {}</source>
    <translation>A expressão de caminho de {} não pôde ser analisada: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="413" />
    <source>{} path expression failed for stratum {}: {}</source>
    <translation>A expressão de caminho de {} falhou para o estrato {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="419" />
    <source>{} path expression returned NULL for stratum {}.</source>
    <translation>A expressão de caminho de {} retornou NULL para o estrato {}.</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="428" />
    <source>Invalid {} path for stratum {}: {}</source>
    <translation>Caminho de {} inválido para o estrato {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="455" />
    <source>Zip paths differ only by letter case (they would overwrite each other on Windows): {}</source>
    <translation>Os caminhos de zip diferem apenas por maiúsculas/minúsculas (sobrescreveriam uns aos outros no Windows): {}</translation>
  </message>
  <message>
    <location filename="../../processing/strata.py" line="471" />
    <source>GeoPackage paths collide inside zip {}: {}</source>
    <translation>Os caminhos de GeoPackage colidem dentro do zip {}: {}</translation>
  </message>
</context><context>
  <name>StratifiedPackager</name>
  <message>
    <location filename="../../main.py" line="72" />
    <source>Plugin initialized successfully.</source>
    <translation>Complemento iniciado com sucesso.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="97" />
    <source>Help</source>
    <translation>Ajuda</translation>
  </message>
  <message>
    <location filename="../../main.py" line="107" />
    <source>Settings</source>
    <translation>Configurações</translation>
  </message>
  <message>
    <location filename="../../main.py" line="120" />
    <source>Project defaults…</source>
    <translation>Padrões do projeto…</translation>
  </message>
  <message>
    <location filename="../../main.py" line="131" />
    <source>Configure layers for packaging…</source>
    <translation>Configurar camadas para empacotamento…</translation>
  </message>
  <message>
    <location filename="../../main.py" line="164" />
    <source>Could not find QGIS plugin help menu to add documentation link.</source>
    <translation>Não foi possível encontrar o menu de ajuda de complementos do QGIS para adicionar o link da documentação.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="176" />
    <source>{} - Documentation</source>
    <translation>{} - Documentação</translation>
  </message>
  <message>
    <location filename="../../main.py" line="200" />
    <source>Processing provider added successfully.</source>
    <translation>Provedor de processamento adicionado com sucesso.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="203" />
    <source>Failed to add processing provider.</source>
    <translation>Falha ao adicionar o provedor de processamento.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="206" />
    <source>Could not access QGIS processing registry to add provider.</source>
    <translation>Não foi possível acessar o registro de processamento do QGIS para adicionar o provedor.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="217" />
    <source>Failed to tear down the plugin settings node.</source>
    <translation>Falha ao desmontar o nó de configurações do complemento.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="227" />
    <source>Failed to tear down the plugin logging handler.</source>
    <translation>Falha ao desmontar o manipulador de registro (log) do complemento.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="250" />
    <source>Failed to remove processing provider during plugin unload.</source>
    <translation>Falha ao remover o provedor de processamento durante a descarga do complemento.</translation>
  </message>
  <message>
    <location filename="../../main.py" line="252" />
    <source>Could not access QGIS processing registry to remove provider.</source>
    <translation>Não foi possível acessar o registro de processamento do QGIS para remover o provedor.</translation>
  </message>
</context><context>
  <name>StratifiedPackagerAlgorithm</name>
  <message>
    <location filename="../../processing/algorithm.py" line="356" />
    <source>{} does not parse: {}</source>
    <translation>{} não pôde ser analisado: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="385" />
    <source>This algorithm requires an open project (use --project_path).</source>
    <translation>Este algoritmo requer um projeto aberto (use --project_path).</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1869" />
    <location filename="../../processing/algorithm.py" line="1510" />
    <location filename="../../processing/algorithm.py" line="1360" />
    <location filename="../../processing/algorithm.py" line="1012" />
    <location filename="../../processing/algorithm.py" line="394" />
    <source>Operation was canceled.</source>
    <translation>A operação foi cancelada.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="483" />
    <source>OUTPUT_DIRECTORY is required.</source>
    <translation>OUTPUT_DIRECTORY é obrigatório.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="570" />
    <source>Cannot determine eligible layers: {}</source>
    <translation>Não foi possível determinar as camadas elegíveis: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="594" />
    <source>Plugin layers cannot be packaged; excluded: {}</source>
    <translation>Camadas de complemento não podem ser empacotadas; excluídas: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="600" />
    <source>Layers riding only in the embedded project (remote/annotation/live virtual): {}</source>
    <translation>Camadas presentes apenas no projeto incorporado (remota/anotação/virtual ativa): {}</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="635" />
    <source>LAYERS resolved %n entry(s) onto a layer already selected: {}. Layers sharing a data source are indistinguishable when selected by source; select them by layer id (or leave LAYERS empty) to package each one.</source>
    <translation>
      <numerusform>LAYERS resolveu %n entrada para uma camada já selecionada: {}. Camadas que compartilham uma origem de dados são indistinguíveis quando selecionadas pela origem; selecione-as pelo id da camada (ou deixe LAYERS vazio) para empacotar cada uma.</numerusform>
      <numerusform>LAYERS resolveu %n entradas para uma camada já selecionada: {}. Camadas que compartilham uma origem de dados são indistinguíveis quando selecionadas pela origem; selecione-as pelo id da camada (ou deixe LAYERS vazio) para empacotar cada uma.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="690" />
    <source>STRATIFICATION_LAYER is required unless EXPORT_FULL_PACKAGE is enabled (then only the full package is built).</source>
    <translation>STRATIFICATION_LAYER é obrigatório, a menos que EXPORT_FULL_PACKAGE esteja ativado (nesse caso, apenas o pacote completo é gerado).</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="704" />
    <source>The stratification layer yielded no strata.</source>
    <translation>A camada de estratificação não produziu nenhum estrato.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="707" />
    <source>No strata to package (the stratification layer is empty).</source>
    <translation>Nenhum estrato para empacotar (a camada de estratificação está vazia).</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="710" />
    <source>Resolved %n strata </source>
    <translation>
      <numerusform>%n estrato resolvido </numerusform>
      <numerusform>%n estratos resolvidos </numerusform>
    </translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="711" />
    <source>into %n zip(s).</source>
    <translation>
      <numerusform>em %n zip.</numerusform>
      <numerusform>em %n zips.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="727" />
    <source>WARM_START_DIR is required when warm start is enabled.</source>
    <translation>WARM_START_DIR é obrigatório quando o início a quente está ativado.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="731" />
    <source>Warm start is enabled but no packaged layer is warm_marked — a warm run with nothing warm is always a misconfiguration.</source>
    <translation>O início a quente está ativado, mas nenhuma camada empacotada está marcada como warm_marked — uma execução a quente sem nada quente é sempre um erro de configuração.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="756" />
    <source>Custom layer name expression for layer {} does not parse: {}</source>
    <translation>A expressão de nome de camada personalizado para a camada {} não pôde ser analisada: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="786" />
    <source>Invalid FULL_PACKAGE_PATH: {}</source>
    <translation>FULL_PACKAGE_PATH inválido: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="831" />
    <source>Existing outputs (OVERWRITE_MODE = error): {}</source>
    <translation>Saídas existentes (OVERWRITE_MODE = error): {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="852" />
    <source>Skipping existing output {}.zip</source>
    <translation>Ignorando saída existente {}.zip</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="873" />
    <source>EXTRA_DIR does not exist or is not a directory: {}</source>
    <translation>EXTRA_DIR não existe ou não é um diretório: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="890" />
    <source>EXTRA_DIR entries collide with reserved zip content: {}</source>
    <translation>As entradas de EXTRA_DIR colidem com conteúdo reservado do zip: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="933" />
    <source>Removed stale build directory: {}</source>
    <translation>Diretório de construção obsoleto removido: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="958" />
    <source>Could not fully remove the build directory: {}</source>
    <translation>Não foi possível remover completamente o diretório de construção: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1002" />
    <source>Duplicate layer name; table renamed to {} for layer {}</source>
    <translation>Nome de camada duplicado; tabela renomeada para {} para a camada {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1014" />
    <source>Preparing layer {}/{}: {}</source>
    <translation>Preparando a camada {}/{}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1041" />
    <source>Layer {}: its copied source file also backs other layers ({}) — the copy drags the whole container.</source>
    <translation>Camada {}: seu arquivo de origem copiado também serve a outras camadas ({}) — a cópia arrasta o contêiner inteiro.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1093" />
    <source>The project has no relation manager.</source>
    <translation>O projeto não tem gerenciador de relações.</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="1269" />
    <source>Warm cache unusable for %n stratum(s) ({}) — staging proceeds so cold fallbacks read local copies.</source>
    <translation>
      <numerusform>Cache quente inutilizável para %n estrato ({}) — as cópias preparadas seguem sendo geradas para que os retornos a frio leiam cópias locais.</numerusform>
      <numerusform>Cache quente inutilizável para %n estratos ({}) — as cópias preparadas seguem sendo geradas para que os retornos a frio leiam cópias locais.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1293" />
    <source>layer {}: stage variable {}</source>
    <translation>camada {}: variável de preparação {}</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="1346" />
    <source>Skipping staging for %n warm-seeded group(s) — the warm cache covers every stratum.</source>
    <translation>
      <numerusform>Pulando a cópia preparada de %n grupo semeado a quente — o cache quente cobre todos os estratos.</numerusform>
      <numerusform>Pulando a cópia preparada de %n grupos semeados a quente — o cache quente cobre todos os estratos.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1362" />
    <source>Staging layer {}/{}: {}</source>
    <translation>Gerando a cópia preparada da camada {}/{}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1574" />
    <location filename="../../processing/algorithm.py" line="1446" />
    <source>could not index staged key fields for {}: {}</source>
    <translation>não foi possível indexar os campos-chave preparados de {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1515" />
    <source>Staging relation-chain layer: {}</source>
    <translation>Gerando a cópia preparada da camada da cadeia de relações: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1529" />
    <source>Could not stage relation-chain layer {} ({}); its hops will be queried from the project instead.</source>
    <translation>Não foi possível gerar a cópia preparada da camada {} da cadeia de relações ({}); seus saltos serão consultados no projeto.</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="1582" />
    <source>Staged relation-chain layer {}: %n feature(s) copied.</source>
    <translation>
      <numerusform>Camada {} da cadeia de relações preparada: %n feição copiada.</numerusform>
      <numerusform>Camada {} da cadeia de relações preparada: %n feições copiadas.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1598" />
    <source>Layer {} could not be cloned.</source>
    <translation>Não foi possível clonar a camada {}.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1615" />
    <source>Staged copy of layer {} cannot be re-opened.</source>
    <translation>A cópia preparada da camada {} não pode ser reaberta.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1728" />
    <source>layer {}: excluded_fields is not a JSON list: {}</source>
    <translation>camada {}: excluded_fields não é uma lista JSON: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1734" />
    <source>layer {}: excluded_fields must be a JSON list of names</source>
    <translation>camada {}: excluded_fields deve ser uma lista JSON de nomes</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="1866" />
    <source>Building %n strata.</source>
    <translation>
      <numerusform>Construindo %n estrato.</numerusform>
      <numerusform>Construindo %n estratos.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1886" />
    <source>Run finished with failures — strata: [{}]; zips: [{}]; warm caches: [{}]</source>
    <translation>Execução concluída com falhas — estratos: [{}]; zips: [{}]; caches quentes: [{}]</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/algorithm.py" line="1940" />
    <source>Updating %n warm cache(s) before the deliverables.</source>
    <translation>
      <numerusform>Atualizando %n cache quente antes dos entregáveis.</numerusform>
      <numerusform>Atualizando %n caches quentes antes dos entregáveis.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1945" />
    <source>Warm cache {}/{}: {}</source>
    <translation>Cache quente {}/{}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1963" />
    <source>Failed to remove workdir copy of warm geopackage {}</source>
    <translation>Falha ao remover a cópia de trabalho do geopackage quente {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="1974" />
    <source>Stratum {}/{}: {}</source>
    <translation>Estrato {}/{}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2039" />
    <source>Stratum {}: cold fallback ({}).</source>
    <translation>Estrato {}: retorno a frio ({}).</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2210" />
    <location filename="../../processing/algorithm.py" line="2046" />
    <source>Stratum {} failed: {}</source>
    <translation>Falha no estrato {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2078" />
    <source>warm cache not written: {}</source>
    <translation>cache quente não gravado: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2082" />
    <source>Stratum {}: warm cache not written ({}).</source>
    <translation>Estrato {}: cache quente não gravado ({}).</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2107" />
    <source>Published {}</source>
    <translation>Publicado {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2111" />
    <source>Zip {} failed: {}</source>
    <translation>Falha no zip {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2150" />
    <source>Zip {} skipped: every member stratum failed.</source>
    <translation>Zip {} ignorado: todos os estratos membros falharam.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2159" />
    <source>Stratum {}: WAL checkpoint incomplete before zipping.</source>
    <translation>Estrato {}: checkpoint do WAL incompleto antes da compactação.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2169" />
    <source>Zipping {}.zip in the background.</source>
    <translation>Compactando {}.zip em segundo plano.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2198" />
    <source>Stratum {}: writing embedded project.</source>
    <translation>Estrato {}: gravando o projeto incorporado.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2208" />
    <source>Failed to remove gpkg of failed stratum {}.</source>
    <translation>Falha ao remover o gpkg do estrato com falha {}.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2220" />
    <source>Stratum {}: could not pre-enable WAL journaling.</source>
    <translation>Estrato {}: não foi possível pré-ativar o modo WAL.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2232" />
    <source>Stratum {}: embedded project not written; shipping data without it ({}).</source>
    <translation>Estrato {}: projeto incorporado não gravado; enviando os dados sem ele ({}).</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2505" />
    <source>Could not create the run report output.</source>
    <translation>Não foi possível criar a saída do relatório da execução.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2510" />
    <source>Could not write a run report row.</source>
    <translation>Não foi possível gravar uma linha do relatório da execução.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2511" />
    <source>Run report written to {}</source>
    <translation>Relatório da execução gravado em {}</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2526" />
    <source>Package project</source>
    <translation>Empacotar projeto</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2531" />
    <source>Partitions the project's layers against a stratification layer and emits one zipped GeoPackage per stratum.</source>
    <translation>Particiona as camadas do projeto de acordo com uma camada de estratificação e emite um GeoPackage compactado em zip por estrato.</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2544" />
    <source>&lt;p&gt;Partitions the open project's layers against a &lt;b&gt;stratification layer&lt;/b&gt; (one stratum per feature) and writes &lt;b&gt;one zipped GeoPackage per stratum&lt;/b&gt; into the output directory. Each layer's features are matched to strata either by &lt;b&gt;attribute&lt;/b&gt; (following chains of project relations) or &lt;b&gt;spatially&lt;/b&gt; (one or more predicates, including raw DE-9IM patterns, combined with OR), chosen per layer.&lt;/p&gt;&lt;h3&gt;Key parameters&lt;/h3&gt;&lt;ul&gt;&lt;li&gt;&lt;b&gt;Layers to package&lt;/b&gt; — leave empty to package every eligible layer not marked with the &lt;code&gt;stratified_packager_exclude&lt;/code&gt; variable.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Stratification layer&lt;/b&gt; and &lt;b&gt;Stratum name expression&lt;/b&gt; — the partition source and how each stratum is named (empty = feature id). Naming and path expressions can use &lt;code&gt;@stratum_name&lt;/code&gt;, &lt;code&gt;@stratum_name_sanitized&lt;/code&gt;, &lt;code&gt;@gpkg_path&lt;/code&gt; and &lt;code&gt;@gpkg_name&lt;/code&gt;.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Output directory&lt;/b&gt; — where zips are published (atomic .part rename).&lt;/li&gt;&lt;li&gt;&lt;b&gt;Existing outputs&lt;/b&gt; — overwrite, error, or skip-existing.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Embed a project per stratum&lt;/b&gt; — none, gpkg (stored inside the package), or qgz (beside it); styles, metadata, relations and auxiliary files are bundled.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Also export the full package&lt;/b&gt; — additionally emit the unpartitioned dataset as a pseudo-stratum.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Dry run&lt;/b&gt; — validate and report without writing any packages.&lt;/li&gt;&lt;/ul&gt;&lt;h3&gt;Per-layer variables&lt;/h3&gt;&lt;p&gt;Edit under &lt;i&gt;Layer Properties &amp;gt; Variables&lt;/i&gt;, the per-layer plugin page, or the plugin's &lt;i&gt;Configure layers for packaging&lt;/i&gt; dialog:&lt;/p&gt;</source>
    <translation>&lt;p&gt;Particiona as camadas do projeto aberto contra uma &lt;b&gt;camada de estratificação&lt;/b&gt; (um estrato por feição) e grava &lt;b&gt;um GeoPackage zipado por estrato&lt;/b&gt; no diretório de saída. As feições de cada camada são associadas aos estratos por &lt;b&gt;atributo&lt;/b&gt; (seguindo cadeias de relações do projeto) ou &lt;b&gt;espacialmente&lt;/b&gt; (um ou mais predicados, incluindo padrões DE-9IM brutos, combinados com OR), à escolha por camada.&lt;/p&gt;&lt;h3&gt;Parâmetros principais&lt;/h3&gt;&lt;ul&gt;&lt;li&gt;&lt;b&gt;Camadas a empacotar&lt;/b&gt; — deixe vazio para empacotar todas as camadas elegíveis sem a variável &lt;code&gt;stratified_packager_exclude&lt;/code&gt;.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Camada de estratificação&lt;/b&gt; e &lt;b&gt;Expressão do nome do estrato&lt;/b&gt; — a origem da partição e como cada estrato é nomeado (vazio = id da feição). As expressões de nomes e caminhos podem usar &lt;code&gt;@stratum_name&lt;/code&gt;, &lt;code&gt;@stratum_name_sanitized&lt;/code&gt;, &lt;code&gt;@gpkg_path&lt;/code&gt; e &lt;code&gt;@gpkg_name&lt;/code&gt;.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Diretório de saída&lt;/b&gt; — onde os zips são publicados (renomeação .part atômica).&lt;/li&gt;&lt;li&gt;&lt;b&gt;Saídas existentes&lt;/b&gt; — overwrite, error ou skip-existing.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Incorporar um projeto por estrato&lt;/b&gt; — none, gpkg (armazenado dentro do pacote) ou qgz (ao lado dele); estilos, metadados, relações e arquivos auxiliares são incluídos.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Exportar também o pacote completo&lt;/b&gt; — emite adicionalmente o conjunto de dados não particionado como pseudoestrato.&lt;/li&gt;&lt;li&gt;&lt;b&gt;Simulação&lt;/b&gt; — validar e relatar sem gravar nenhum pacote.&lt;/li&gt;&lt;/ul&gt;&lt;h3&gt;Variáveis por camada&lt;/h3&gt;&lt;p&gt;Edite-as em &lt;i&gt;Propriedades da camada &amp;gt; Variáveis&lt;/i&gt;, na página por camada do plugin ou no diálogo &lt;i&gt;Configurar camadas para empacotamento&lt;/i&gt;:&lt;/p&gt;</translation>
  </message>
  <message>
    <location filename="../../processing/algorithm.py" line="2575" />
    <source>&lt;h3&gt;Defaults and precedence&lt;/h3&gt;&lt;p&gt;Every omitted parameter resolves through &lt;b&gt;explicit input &amp;gt; project variable (&lt;code&gt;stratified_packager_&amp;lt;param&amp;gt;&lt;/code&gt;) &amp;gt; plugin setting &amp;gt; builtin default&lt;/b&gt;. Project- and layer-scope values are editable from the plugin's Options page, the Project Properties page and the per-layer page.&lt;/p&gt;&lt;h3&gt;Warm cache&lt;/h3&gt;&lt;p&gt;With a warm-cache directory, &lt;b&gt;Use warm start&lt;/b&gt; begins each stratum GeoPackage from a cached copy and appends only non-warm-marked layers; &lt;b&gt;Update warm cache&lt;/b&gt; first writes every stratum's cache file, then builds the deliverables seeded from that fresh cache — an interrupted run still leaves a complete, reusable cache. A cached file that no longer matches its warm-marked tables falls back to a cold build for that stratum (reported as cold-fallback).&lt;/p&gt;&lt;h3&gt;Running headless (qgis_process)&lt;/h3&gt;&lt;p&gt;Pass &lt;code&gt;--project_path&lt;/code&gt;: the algorithm requires a project. The Processing framework re-instantiates the algorithm after the project loads, so project-variable and plugin-setting defaults resolve correctly without a GUI. &lt;code&gt;QgsSettings&lt;/code&gt; is per-profile, so qgis_process uses the default profile unless overridden.&lt;/p&gt;</source>
    <translation>&lt;h3&gt;Padrões e precedência&lt;/h3&gt;&lt;p&gt;Cada parâmetro omitido é resolvido por &lt;b&gt;entrada explícita &amp;gt; variável de projeto (&lt;code&gt;stratified_packager_&amp;lt;param&amp;gt;&lt;/code&gt;) &amp;gt; configuração do plugin &amp;gt; padrão embutido&lt;/b&gt;. Os valores de escopo de projeto e de camada são editáveis na página de Opções do plugin, na página de Propriedades do projeto e na página por camada.&lt;/p&gt;&lt;h3&gt;Cache quente&lt;/h3&gt;&lt;p&gt;Com um diretório de cache quente, &lt;b&gt;Usar partida a quente&lt;/b&gt; inicia cada GeoPackage de estrato a partir de uma cópia em cache e acrescenta apenas as camadas não marcadas; &lt;b&gt;Atualizar o cache quente&lt;/b&gt; primeiro grava o arquivo de cache de cada estrato e só então constrói os entregáveis semeados a partir desse cache fresco — uma execução interrompida ainda deixa um cache completo e reutilizável. Um arquivo em cache que não corresponda mais às suas tabelas marcadas retorna a uma construção a frio para aquele estrato (relatado como cold-fallback).&lt;/p&gt;&lt;h3&gt;Execução sem interface (qgis_process)&lt;/h3&gt;&lt;p&gt;Passe &lt;code&gt;--project_path&lt;/code&gt;: o algoritmo requer um projeto. O framework de Processing reinstancia o algoritmo depois que o projeto é carregado, de modo que os padrões de variáveis de projeto e configurações do plugin são resolvidos corretamente sem GUI. &lt;code&gt;QgsSettings&lt;/code&gt; é por perfil, então o qgis_process usa o perfil padrão a menos que outro seja indicado.&lt;/p&gt;</translation>
  </message>
  <message>
    <location filename="../../processing/dedup.py" line="74" />
    <source>Deduplicating shared source into table {}: {}</source>
    <translation>Desduplicando origem compartilhada na tabela {}: {}</translation>
  </message>
  <message>
    <location filename="../../processing/dedup.py" line="92" />
    <source>Could not clear the subset of shared table {}.</source>
    <translation>Não foi possível limpar o subconjunto da tabela compartilhada {}.</translation>
  </message>
  <message>
    <location filename="../../processing/dedup.py" line="129" />
    <source>Shared table {} is warm-marked through {}; every member of the dedup group follows.</source>
    <translation>A tabela compartilhada {} está marcada como quente através de {}; todos os membros do grupo de deduplicação a acompanham.</translation>
  </message>
  <message>
    <location filename="../../processing/material.py" line="228" />
    <source>layer {}: warm_marked variable {}</source>
    <translation>camada {}: variável warm_marked {}</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="153" />
    <source>(bool) — skip this layer when Layers is empty.</source>
    <translation>(bool) — ignora esta camada quando LAYERS está vazio.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="161" />
    <source>(expression) — display name for this layer in the embedded per-stratum project; evaluated per stratum and may use &lt;code&gt;@stratum_name&lt;/code&gt; / &lt;code&gt;@stratum_name_sanitized&lt;/code&gt; (empty = original name; no effect without an embedded project).</source>
    <translation>(expressão) — nome de exibição desta camada no projeto incorporado por estrato; avaliado por estrato e pode usar &lt;code&gt;@stratum_name&lt;/code&gt; / &lt;code&gt;@stratum_name_sanitized&lt;/code&gt; (vazio = nome original; sem efeito sem um projeto incorporado).</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="173" />
    <source>— auto, attribute, spatial or whole_export.</source>
    <translation>— auto, attribute, spatial ou whole_export.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="182" />
    <source>— auto, or a comma-separated list (combined with OR) of named predicates (intersects, contains, within, overlaps, crosses, touches) and 9-character DE-9IM patterns.</source>
    <translation>— auto, ou uma lista separada por vírgulas (combinada com OR) de predicados nomeados (intersects, contains, within, overlaps, crosses, touches) e padrões DE-9IM de 9 caracteres.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="194" />
    <source>— JSON list of fields to drop from the exported table.</source>
    <translation>— lista JSON de campos a remover da tabela exportada.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="204" />
    <source>(bool or auto) — force or forbid staging this layer's data into a local copy before the per-stratum writes; auto follows STAGE_PROVIDERS.</source>
    <translation>(bool ou auto) — força ou impede gerar a cópia preparada local dos dados desta camada antes das gravações por estrato; auto segue STAGE_PROVIDERS.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="215" />
    <source>(bool) — layer belongs to the warm cache.</source>
    <translation>(bool) — a camada pertence ao cache quente.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="224" />
    <source>(bool) — write a virtual layer's features into each package instead of keeping the layer live (with its query) in the embedded project.</source>
    <translation>(bool) — grava as feições de uma camada virtual em cada pacote em vez de manter a camada viva (com sua consulta) no projeto incorporado.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="236" />
    <source>— JSON list of relation ids pinning an otherwise ambiguous attribute chain.</source>
    <translation>— lista JSON de ids de relações que fixa uma cadeia de atributos que de outro modo seria ambígua.</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="322" />
    <source>Layer Configuration</source>
    <translation>Configuração da camada</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="327" />
    <source>Symbology</source>
    <translation>Simbologia</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="332" />
    <source>3D Symbology</source>
    <translation>Simbologia 3D</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="337" />
    <source>Labels</source>
    <translation>Rótulos</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="342" />
    <source>Fields</source>
    <translation>Campos</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="347" />
    <source>Attribute Form</source>
    <translation>Formulário de atributos</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="352" />
    <source>Actions</source>
    <translation>Ações</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="357" />
    <source>Map Tips</source>
    <translation>Dicas de mapa</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="362" />
    <source>Diagrams</source>
    <translation>Diagramas</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="367" />
    <source>Attribute Table Configuration</source>
    <translation>Configuração da tabela de atributos</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="372" />
    <source>Rendering</source>
    <translation>Renderização</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="377" />
    <source>Custom Properties</source>
    <translation>Propriedades personalizadas</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="382" />
    <source>Geometry Options</source>
    <translation>Opções de geometria</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="387" />
    <source>Relations</source>
    <translation>Relações</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="392" />
    <source>Temporal Properties</source>
    <translation>Propriedades temporais</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="397" />
    <source>Legend Settings</source>
    <translation>Configurações da legenda</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="402" />
    <source>Elevation Properties</source>
    <translation>Propriedades de elevação</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="407" />
    <source>Notes</source>
    <translation>Notas</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="588" />
    <source>Layers to package (empty = all eligible layers)</source>
    <translation>Camadas a empacotar (vazio = todas as camadas elegíveis)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="597" />
    <source>Stratification layer (one stratum per feature)</source>
    <translation>Camada de estratificação (um estrato por feição)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="605" />
    <source>Stratum name expression (empty = feature id)</source>
    <translation>Expressão de nome do estrato (vazio = id da feição)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="613" />
    <source>Only selected stratification features become strata</source>
    <translation>Apenas feições de estratificação selecionadas tornam-se estratos</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="622" />
    <source>GeoPackage path expression (empty = sanitized stratum name)</source>
    <translation>Expressão de caminho do GeoPackage (vazio = nome do estrato higienizado)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="632" />
    <source>Zip path expression (empty = GeoPackage name)</source>
    <translation>Expressão de caminho do zip (vazio = nome do GeoPackage)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="641" />
    <source>Output directory</source>
    <translation>Diretório de saída</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="647" />
    <source>Zip compression level (0 = store uncompressed)</source>
    <translation>Nível de compressão do zip (0 = armazenar sem compressão)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="656" />
    <source>Existing outputs</source>
    <translation>Saídas existentes</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="663" />
    <source>Embed a QGIS project per stratum</source>
    <translation>Incorporar um projeto QGIS por estrato</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="672" />
    <source>Build in a temporary folder, publish zips atomically</source>
    <translation>Construir em uma pasta temporária, publicar os zips atomicamente</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="682" />
    <source>Include layer styles</source>
    <translation>Incluir estilos das camadas</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="689" />
    <source>Style categories to copy (none checked = all)</source>
    <translation>Categorias de estilo a copiar (nenhuma marcada = todas)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="698" />
    <source>Include layer metadata</source>
    <translation>Incluir metadados das camadas</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="705" />
    <source>Keep layers with no matching features as empty tables</source>
    <translation>Manter camadas sem feições correspondentes como tabelas vazias</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="715" />
    <source>Write layers sharing a data source as one table</source>
    <translation>Gravar camadas que compartilham uma fonte de dados como uma única tabela</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="724" />
    <source>Stage every layer of these data providers (see the stage layer variable)</source>
    <translation>Gerar cópia preparada de todas as camadas destes provedores de dados (ver a variável de camada stage)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="734" />
    <source>Also export the full (unpartitioned) package</source>
    <translation>Exportar também o pacote completo (não particionado)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="743" />
    <source>Full package path (empty = &lt;project name&gt;_full)</source>
    <translation>Caminho do pacote completo (vazio = &lt;nome do projeto&gt;_full)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="751" />
    <source>Write a report.csv into each published zip</source>
    <translation>Gravar um report.csv em cada zip publicado</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="760" />
    <source>Extra files directory (copied into every zip root)</source>
    <translation>Diretório de arquivos extras (copiado para a raiz de cada zip)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="768" />
    <source>Warm cache directory</source>
    <translation>Diretório do cache quente</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="774" />
    <source>Warm cache mode</source>
    <translation>Modo do cache quente</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="781" />
    <source>Write a .sha256 file next to each zip</source>
    <translation>Gravar um arquivo .sha256 ao lado de cada zip</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="790" />
    <source>Dry run (validate and report only, write no packages)</source>
    <translation>Simulação (apenas validar e relatar, sem gravar pacotes)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="1268" />
    <source>Run report (loaded as a memory layer when no path is given)</source>
    <translation>Relatório da execução (carregado como camada em memória quando nenhum caminho é fornecido)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="1387" />
    <source>Published zip paths (JSON array)</source>
    <translation>Caminhos dos zips publicados (array JSON)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="1393" />
    <source>Strata resolved</source>
    <translation>Estratos resolvidos</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="1396" />
    <source>Zips published</source>
    <translation>Zips publicados</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="1400" />
    <source>Failed strata (JSON array)</source>
    <translation>Estratos com falha (array JSON)</translation>
  </message>
  <message numerus="yes">
    <location filename="../../processing/reporting.py" line="210" />
    <source>Layer {}: %n feature(s) match no stratum.</source>
    <translation>
      <numerusform>Camada {}: %n feição não corresponde a estrato algum.</numerusform>
      <numerusform>Camada {}: %n feições não correspondem a estrato algum.</numerusform>
    </translation>
  </message>
  <message>
    <location filename="../../processing/virtual.py" line="106" />
    <source>Virtual layer {} is materialized but queries non-local source(s) ({}). Its query re-runs against them for every stratum, which on a database provider means many round-trips and may exhaust the provider's connection pool. Consider pushing the join into the source — a subset filter, a view, or a materialized view — and packaging that layer instead.</source>
    <translation>A camada virtual {} é materializada mas consulta fontes não locais ({}). Sua consulta é reexecutada contra elas a cada estrato, o que em um provedor de banco de dados significa muitas idas e voltas e pode esgotar o pool de conexões do provedor. Considere levar a junção para a fonte — um filtro de subconjunto, uma visão ou uma visão materializada — e empacotar essa camada no lugar.</translation>
  </message>
  <message>
    <location filename="../../processing/virtual.py" line="148" />
    <source>layer {}: materialize_virtual_layer {} is not a boolean: {}</source>
    <translation>camada {}: materialize_virtual_layer {} não é um booleano: {}</translation>
  </message>
  <message>
    <location filename="../../processing/virtual.py" line="165" />
    <source>Virtual layer {} references sources not packaged ({}); materializing it instead of keeping it live in the embedded project.</source>
    <translation>A camada virtual {} referencia fontes não empacotadas ({}); ela será materializada em vez de mantida ativa no projeto incorporado.</translation>
  </message>
</context><context>
  <name>StratifiedPackagerProvider</name>
  <message>
    <location filename="../../processing/provider.py" line="57" />
    <source>Failed to register the %s algorithm.</source>
    <translation>Falha ao registrar o algoritmo %s.</translation>
  </message>
  <message>
    <location filename="../../processing/provider.py" line="76" />
    <source>No project available; default-refresh signals not connected.</source>
    <translation>Nenhum projeto disponível; sinais de atualização de padrões não conectados.</translation>
  </message>
</context><context>
  <name>StratifiedPackagerWidgets</name>
  <message>
    <location filename="../../gui/widgets.py" line="82" />
    <source>Overwrite</source>
    <translation>Sobrescrever</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="85" />
    <source>Error if exists</source>
    <translation>Erro se existir</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="88" />
    <source>Skip existing</source>
    <translation>Ignorar existentes</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="95" />
    <source>None</source>
    <translation>Nenhum</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="96" />
    <source>Embedded in GeoPackage</source>
    <translation>Incorporado no GeoPackage</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="99" />
    <source>Standalone .qgz project</source>
    <translation>Projeto .qgz autônomo</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="106" />
    <source>Off</source>
    <translation>Desligado</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="107" />
    <source>Start from warm cache</source>
    <translation>Iniciar a partir do cache quente</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="110" />
    <source>Refresh warm cache</source>
    <translation>Atualizar o cache quente</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="117" />
    <source>By attribute (relations)</source>
    <translation>Por atributo (relações)</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="120" />
    <source>Spatial</source>
    <translation>Espacial</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="123" />
    <source>Whole export</source>
    <translation>Exportação completa</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="140" />
    <source>inherit (= {})</source>
    <translation>herdar (= {})</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="142" />
    <source>inherit</source>
    <translation>herdar</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="417" />
    <source>all</source>
    <translation>todas</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="515" />
    <source>DE-9IM pattern(s)…</source>
    <translation>Padrão(ões) DE-9IM…</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="522" />
    <source>DE-9IM:</source>
    <translation>DE-9IM:</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="614" />
    <source>Invalid DE-9IM pattern(s): {}</source>
    <translation>Padrão(ões) DE-9IM inválido(s): {}</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="804" />
    <source>not set</source>
    <translation>não definido</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="891" />
    <source>Enabled</source>
    <translation>Ativado</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="892" />
    <source>Disabled</source>
    <translation>Desativado</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="1300" />
    <source>auto</source>
    <translation>auto</translation>
  </message>
  <message>
    <location filename="../../gui/widgets.py" line="1311" />
    <source>keep original</source>
    <translation>manter original</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="152" />
    <source>Exclude layer</source>
    <translation>Excluir camada</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="160" />
    <source>Custom layer name (expression)</source>
    <translation>Nome de camada personalizado (expressão)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="172" />
    <source>Matching method</source>
    <translation>Método de correspondência</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="181" />
    <source>Spatial predicate(s)</source>
    <translation>Predicado(s) espacial(is)</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="193" />
    <source>Excluded fields</source>
    <translation>Campos excluídos</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="203" />
    <source>Stage layer data</source>
    <translation>Preparar dados da camada</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="214" />
    <source>Warm-marked</source>
    <translation>Marcado como quente</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="223" />
    <source>Materialize virtual layer</source>
    <translation>Materializar camada virtual</translation>
  </message>
  <message>
    <location filename="../../processing/params.py" line="235" />
    <source>Relation path (JSON ids)</source>
    <translation>Caminho de relação (ids JSON)</translation>
  </message>
</context><context>
  <name>dlg_stratified_packager_layers_table</name>
  <message>
    <location filename="../../gui/dlg_layers_table.ui" line="0" />
    <source>Stratified Packager - Configure layers</source>
    <translation>Stratified Packager - Configurar camadas</translation>
  </message>
  <message>
    <location filename="../../gui/dlg_layers_table.ui" line="0" />
    <source>Per-layer packaging settings. An empty cell inherits the builtin default; matching columns apply to vector layers only.</source>
    <translation>Configurações de empacotamento por camada. Uma célula vazia herda o padrão interno; as colunas de correspondência aplicam-se apenas a camadas vetoriais.</translation>
  </message>
  <message>
    <location filename="../../gui/dlg_layers_table.ui" line="0" />
    <source>Plugin settings…</source>
    <translation>Configurações do complemento…</translation>
  </message>
  <message>
    <location filename="../../gui/dlg_layers_table.ui" line="0" />
    <source>Project defaults…</source>
    <translation>Padrões do projeto…</translation>
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
    <translation>Como esta camada participa das execuções do Stratified Packager. Um campo vazio herda o padrão interno (mostrado como espaço reservado).</translation>
  </message>
</context><context>
  <name>wdg_stratified_packager_plugin_options_page</name>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Stratified Packager - Settings</source>
    <translation>Stratified Packager - Configurações</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Algorithm defaults</source>
    <translation>Padrões do algoritmo</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Plugin-wide defaults for the Package project algorithm. A project variable, where set, overrides the value here for that project.</source>
    <translation>Padrões de todo o complemento para o algoritmo Empacotar projeto. Uma variável de projeto, quando definida, substitui o valor aqui para aquele projeto.</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Miscellaneous</source>
    <translation>Diversos</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Report an issue</source>
    <translation>Relatar um problema</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Version used to save settings:</source>
    <translation>Versão usada para salvar as configurações:</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Help</source>
    <translation>Ajuda</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Reset settings to factory defaults</source>
    <translation>Redefinir as configurações para os padrões de fábrica</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Enable debug mode.</source>
    <translation>Ativar o modo de depuração.</translation>
  </message>
  <message>
    <location filename="../../gui/wdg_plugin_options_page.ui" line="0" />
    <source>Debug mode (degraded performances)</source>
    <translation>Modo de depuração (desempenho reduzido)</translation>
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
    <translation>Padrões com escopo de projeto para o Stratified Packager. Um campo vazio herda a configuração do complemento (mostrada como espaço reservado); limpar um campo faz retornar a esse padrão.</translation>
  </message>
</context></TS>
