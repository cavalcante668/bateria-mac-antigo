# Battery Guard — Documentação Técnica

**Projeto:** Battery Guard  
**Plataforma atual:** macOS Monterey / Intel x86_64  
**Estado do projeto:** v0.4 em desenvolvimento  
**Objetivo central:** monitorar a saúde elétrica da bateria e o comportamento computacional do Mac para, futuramente, aplicar proteção adaptativa contra picos de consumo que possam provocar desligamentos abruptos em baterias degradadas.

---

## 1. Visão geral

O Battery Guard nasceu como um monitor de bateria voltado a um MacBook Pro com comportamento elétrico anormal: uma das células/grupos apresenta queda acentuada de tensão sob carga, levando a desligamentos abruptos mesmo quando o estado de carga informado pelo BMS ainda é elevado.

O projeto evoluiu para uma arquitetura de telemetria do sistema, histórico persistente, análise de comportamento e futura atuação preventiva.

A premissa principal é:

> O macOS gerencia recursos para preservar responsividade e estabilidade do sistema. O Battery Guard acrescenta uma variável que o sistema operacional não conhece: o limite elétrico real de uma bateria degradada.

O Battery Guard não substitui o gerenciamento de processos do macOS. Ele pretende funcionar como um supervisor energético adicional.

---

## 2. Objetivos

### 2.1. Objetivos atuais

- Ler informações elétricas da bateria e das células.
- Identificar queda excessiva de tensão em uma célula.
- Calcular diferença de tensão entre células.
- Registrar corrente, potência, carga, temperatura e estado de alimentação.
- Manter histórico em SQLite.
- Exibir dashboard nativo no macOS.
- Exibir estado no menu bar.
- Registrar CPU, RAM, pressão de memória, armazenamento, rede e processos.
- Identificar aplicações com maior impacto computacional.
- Construir uma base histórica para análise posterior.

### 2.2. Objetivos futuros

- Aprender o comportamento normal do computador e de cada aplicação.
- Relacionar carga computacional com resposta elétrica da bateria.
- Prever queda perigosa de C1 antes do desligamento.
- Distinguir picos transitórios de consumo sustentado.
- Recomendar ações de redução de carga.
- Aplicar políticas automáticas e reversíveis em processos elegíveis.
- Medir a eficácia de cada intervenção.
- Arquivar histórico antigo em armazenamento remoto.
- Utilizar OneDrive como camada de armazenamento frio, após medir o ritmo real de crescimento do banco.

---

## 3. Princípios de projeto

### 3.1. Preservar a experiência do macOS

O Battery Guard não deve competir com o scheduler do macOS em situações normais.

A intervenção só deve ocorrer quando existir risco elétrico relevante ou desperdício energético evidente.

### 3.2. Segurança antes de autonomia

O objetivo principal não é simplesmente obter o menor consumo possível.

O objetivo é evitar condições que provoquem afundamento rápido de tensão da célula mais fraca e desligamento inesperado.

### 3.3. Ações graduais e reversíveis

Ordem esperada de intervenção:

1. observar;
2. avisar;
3. reduzir prioridade;
4. limitar atividade em background;
5. suspender temporariamente processos elegíveis;
6. retomar automaticamente quando o risco diminuir.

Encerrar processos deve ser exceção.

### 3.4. Processos críticos são protegidos

Processos essenciais do sistema não devem ser suspensos automaticamente.

Exemplos:

- kernel_task
- launchd
- WindowServer
- powerd
- loginwindow
- coreaudiod
- Battery Guard

### 3.5. Foreground é protegido por padrão

Aplicações em uso ativo pelo usuário não devem ser pausadas automaticamente em operação normal.

Em risco elétrico extremo, o Battery Guard pode recomendar redução ou executar ação previamente autorizada.

---

## 4. Arquitetura atual

```text
Battery Guard.app
        |
        +-- launcher
        |
        +-- native-view.py
        |       |
        |       +-- janela nativa pywebview
        |       +-- menu bar AppKit
        |       +-- ícone dinâmico por estado
        |
        +-- battery-view.py
                |
                +-- servidor HTTP local 127.0.0.1:8765
                +-- coletor de bateria
                +-- dashboard HTML
                +-- API /api
                +-- API /api/system
                +-- process catalog
                +-- histórico
                |
                +-- system_telemetry.py
                        |
                        +-- CPU
                        +-- memória
                        +-- pressão de memória
                        +-- processos
                        +-- aplicações
                        +-- rede
                        +-- armazenamento
```

---

## 5. Componentes

### 5.1. battery-view.py

Responsabilidades principais:

- coletar dados da bateria;
- calcular indicadores elétricos;
- alimentar o histórico;
- persistir dados;
- servir dashboard;
- disponibilizar API local;
- iniciar telemetria do sistema.

O arquivo tornou-se grande e deve evitar receber novos coletores diretamente.

Novos recursos de telemetria devem ser implementados em módulos separados.

### 5.2. native-view.py

Responsável pela integração nativa com o macOS.

Recursos:

- janela nativa;
- execução em background;
- menu bar;
- ícone de status;
- abertura e ocultação da janela;
- menu da aplicação;
- About;
- política Accessory/Regular.

### 5.3. system_telemetry.py

Responsável pela nova telemetria do sistema.

Métricas atualmente previstas/coletadas:

- CPU total;
- load average;
- RAM;
- pressão de memória;
- swap;
- uptime;
- aplicação em foreground;
- interface de rede;
- RX/TX;
- armazenamento;
- processos;
- consolidação por aplicação;
- contexto de alimentação.

### 5.4. process-resolver.py

Resolve nomes técnicos de processos para nomes amigáveis e descrições.

Utiliza a tabela `process_catalog`.

---

## 6. Interface

A interface principal deve manter a separação:

```text
[Bateria] [Sistema]
```

### 6.1. Aba Bateria

A aba de bateria é considerada funcional e deve ser preservada.

Principais dados:

- C1;
- C2;
- C3;
- menor tensão;
- delta entre células;
- corrente;
- potência;
- carga BMS;
- energia útil estimada;
- risco de desligamento;
- C1 projetada;
- temperatura;
- estado AC/bateria;
- histórico;
- processos existentes ligados ao contexto da bateria.

### 6.2. Aba Sistema

Em desenvolvimento.

Áreas planejadas:

- Visão geral;
- CPU;
- memória;
- pressão de memória;
- processos;
- aplicações;
- armazenamento;
- rede;
- análises;
- proteção adaptativa.

---

## 7. Modelo elétrico atual

A bateria apresenta comportamento assimétrico.

A célula/grupo C1 sofre queda significativamente maior sob corrente elevada.

O Battery Guard utiliza indicadores empíricos como:

- tensão mínima;
- delta entre células;
- corrente;
- potência;
- C1 projetada sob carga;
- risco empírico de desligamento.

O risco atual não deve ser interpretado como probabilidade estatística de falha.

É um índice operacional.

---

## 8. Limiares preventivos atuais

Referência operacional usada no projeto:

- aviso quando `MIN <= 3350 mV` e `DELTA >= 400 mV`;
- crítico quando `MIN <= 3250 mV`;
- emergência em torno de `MIN <= 3050 mV`.

Esses valores não representam necessariamente o cutoff físico exato da bateria.

O comportamento observado indica que a combinação entre corrente, sag de C1 e delta é mais informativa que um valor isolado.

---

## 9. Risco empírico

O Battery Guard possui um índice de risco de 0 a 100.

Entradas principais:

- C1 projetada;
- delta;
- corrente.

Estados:

- SEGURO
- ATENÇÃO
- ALERTA
- CRÍTICO

O índice deve evoluir para um modelo adaptativo com base no histórico real.

---

## 10. Banco de dados

Banco: SQLite.

### 10.1. Tabelas originais

#### battery_samples

Histórico de amostras elétricas.

Campos principais:

- timestamp
- c1
- c2
- c3
- min_mv
- delta_mv
- voltage_v
- current_ma
- instant_ma
- power_w
- instant_power_w
- capacity_mah
- max_capacity_mah
- remaining_wh
- percent
- temperature_c
- external_connected
- charging
- system_power_w
- process_json

#### charger_sessions

Registra sessões conectadas ao carregador.

#### process_catalog

Catálogo persistente de processos.

Campos principais:

- technical_name
- friendly_name
- status
- process_type
- description
- source
- source_url
- created_at
- last_checked

### 10.2. Tabelas adicionadas para telemetria de sistema

- schema_meta
- system_inventory
- system_samples
- process_instances
- process_samples
- app_samples
- network_samples
- storage_samples
- thermal_samples
- analysis_events

### 10.3. Tabelas futuras

Planejadas:

- behavior_sessions
- app_baselines
- battery_response_models
- risk_predictions
- policy_actions
- action_outcomes
- protected_processes
- model_state
- archive_queue

---

## 11. Situação atual dos caminhos do banco

Existe uma inconsistência técnica que deve ser resolvida antes da estabilização da v0.4.

Foram observados dois caminhos:

```text
~/battery-history.db
```

e:

```text
~/Library/Application Support/Battery Guard/battery-history.db
```

O servidor live atualmente observado estava utilizando o banco localizado diretamente no diretório HOME.

A arquitetura final deve consolidar tudo em um único banco em:

```text
~/Library/Application Support/Battery Guard/
```

A migração deve ser feita com backup e validação antes de remover qualquer banco antigo.

---

## 12. Crescimento do banco

Antes de habilitar arquivamento remoto, o ritmo real de crescimento precisa ser medido.

Não se deve projetar armazenamento apenas multiplicando a quantidade atual de tabelas pelo intervalo de coleta.

O crescimento depende de:

- número de processos;
- frequência de amostragem;
- tamanho das linhas;
- índices;
- WAL;
- eventos;
- tempo em atividade;
- futuras tabelas de comportamento.

### 12.1. Métricas a acompanhar

- tamanho do arquivo `.db`;
- tamanho de `.db-wal`;
- tamanho de `.db-shm`;
- total ocupado;
- page_count;
- freelist_count;
- page_size;
- crescimento por hora;
- crescimento por dia;
- projeção semanal;
- projeção mensal;
- projeção anual.

### 12.2. Janela mínima

Primeira estimativa útil:

- 24 horas: estimativa preliminar;
- 72 horas: boa aproximação;
- 7 dias: baseline confiável;
- 14–30 dias: planejamento de retenção.

---

## 13. Estratégia de armazenamento futuro

A estratégia prevista é:

```text
HOT
SQLite local
dados recentes e detalhados

WARM
rollups locais
1 min / 5 min / 1 h

COLD
OneDrive
dados históricos fechados e comprimidos
```

O banco SQLite ativo não deve ser sincronizado diretamente.

O armazenamento remoto deve receber snapshots ou arquivos de exportação fechados.

A integração com OneDrive fica deliberadamente adiada até a medição do crescimento real.

---

## 14. Aprendizado comportamental

O futuro Behavior Engine deve aprender:

- consumo típico por aplicação;
- consumo típico por contexto;
- carga em foreground;
- carga em background;
- duração dos picos;
- resposta de C1 à corrente;
- resposta de C1 à potência;
- resposta por faixa de SOC;
- resposta por temperatura;
- recuperação após redução de carga.

O objetivo não é aprender conteúdo do usuário.

Não é necessário armazenar:

- URLs;
- documentos;
- texto digitado;
- mensagens;
- conteúdo de tela.

Basta armazenar contexto computacional e elétrico.

---

## 15. Modelo futuro de previsão

Entradas candidatas:

```text
C1 atual
C2
C3
delta
SOC
corrente
potência
temperatura
inclinação recente de C1
CPU
load
pressão de memória
I/O
rede
foreground
apps dominantes
```

Saídas:

```text
C1 projetada em 15 s
C1 projetada em 30 s
C1 projetada em 60 s
margem elétrica
risco previsto
```

---

## 16. Controle adaptativo

Fluxo esperado:

```text
Telemetria
    |
Histórico
    |
Baseline
    |
Detecção de anomalia
    |
Predição elétrica
    |
Política
    |
Ação
    |
Medição do resultado
    |
Atualização do modelo
```

---

## 17. Política de intervenção planejada

### Nível 0 — normal

Nenhuma ação.

### Nível 1 — observação

Aumenta atenção e coleta contexto.

### Nível 2 — aviso

Informa que determinada carga está elevando o risco.

### Nível 3 — redução

Reduz prioridade de aplicações elegíveis em background.

### Nível 4 — pausa temporária

Suspende processos de background selecionados.

Possível implementação futura:

- SIGSTOP
- SIGCONT

### Nível 5 — proteção emergencial

Aplicada apenas em risco elétrico extremo e com políticas previamente autorizadas.

---

## 18. Avaliação das intervenções

Cada ação deverá ser registrada.

Exemplo:

```text
antes
C1 = 3.31 V
potência = 30 W
Chrome = 62% CPU

ação
redução de carga em background

30 s depois
C1 = 3.39 V
potência = 18 W

resultado
ação eficaz
```

O sistema deve aprender não apenas qual aplicação gera carga, mas também qual intervenção funciona melhor.

---

## 19. Telemetria e privacidade

A filosofia do projeto é minimizar coleta de conteúdo pessoal.

Dados desejados:

- identificador de aplicação;
- processo;
- PID/PPID;
- CPU;
- memória;
- I/O;
- rede agregada;
- foreground/background;
- métricas elétricas.

Dados que não são necessários:

- conteúdo digitado;
- URLs;
- documentos;
- nomes de arquivos pessoais;
- conteúdo de mensagens.

---

## 20. API local

Servidor atual:

```text
http://127.0.0.1:8765
```

Rotas relevantes:

### /api

Estado atual da bateria e histórico do dashboard.

### /api/system

Estado atual da telemetria do sistema.

### /process-catalog

Catálogo de processos.

### /resolve-status

Estado do resolvedor de processos.

---

## 21. Menu bar

O Battery Guard possui integração com menu bar do macOS.

Informações previstas:

```text
Battery Guard
──────────────
Status
C1
C2
C3
Delta
Risco
──────────────
Abrir Battery Guard
Sair
```

O ícone utiliza o estado da bateria para representação visual.

---

## 22. Estados visuais

- SEGURO: verde
- ATENÇÃO: amarelo
- ALERTA: amarelo/vermelho
- CRÍTICO: vermelho

O mesmo estado deve ser reutilizado na interface e no menu bar, evitando lógica duplicada.

---

## 23. Desenvolvimento local

Repositório local:

```text
~/Projects/macbook-battery-guard
```

Pipeline local:

```text
./bg
```

Comandos existentes/planejados:

```text
./bg backup
./bg check
./bg build
./bg install
./bg dev
./bg status
./bg telemetry-test
```

A pipeline deve sempre realizar backup antes de alterações que envolvam schema ou build.

---

## 24. Git e releases

Repositório remoto:

```text
<your-subdomain>/bateria-mac-antigo
```

Branch principal:

```text
main
```

Versão estável conhecida antes da telemetria de sistema:

```text
v0.3.0
```

A série v0.4 está em desenvolvimento.

Não criar tag final da v0.4 antes de validar:

- bateria;
- sistema;
- persistência;
- estabilidade do servidor;
- consumo do próprio Battery Guard;
- migração de banco;
- crescimento do banco.

---

## 25. Roadmap sugerido

### v0.4

Telemetria de sistema.

- CPU
- RAM
- pressão de memória
- processos
- aplicações
- armazenamento
- rede
- histórico
- aba Sistema
- medição do crescimento do SQLite

### v0.5

Behavior Engine.

- baseline por aplicação
- sessões de comportamento
- correlação carga x C1
- resposta por SOC
- identificação de padrões

### v0.6

Predição.

- projeção de C1
- margem elétrica
- previsão de risco
- recomendação preventiva

### v0.7

Otimização assistida.

- sugestões
- políticas
- ações manuais
- avaliação de resultados

### v0.8

Controle automático.

- renice
- limitação de background
- suspensão temporária
- retomada
- proteções

### v1.x

Sistema adaptativo completo.

- aprendizado contínuo
- políticas personalizadas
- armazenamento histórico remoto
- modelos versionados
- feedback de eficácia

---

## 26. Pendências técnicas conhecidas

1. Consolidar os dois caminhos de banco.
2. Finalizar estabilidade da thread de system telemetry.
3. Filtrar processos de instrumentação do ranking.
4. Medir crescimento do banco por pelo menos 72 horas.
5. Definir política de retenção.
6. Criar rollups.
7. Definir formato de exportação histórica.
8. Adiar OneDrive até existirem dados reais de crescimento.
9. Separar progressivamente módulos de `battery-view.py`.
10. Documentar migrations do schema.
11. Criar testes para os indicadores de risco.
12. Criar lista de processos protegidos.
13. Medir o overhead do próprio Battery Guard.

---

## 27. Decisões arquiteturais importantes

### ADR-001 — Banco operacional permanece local

O SQLite ativo não será executado sobre diretório sincronizado.

### ADR-002 — OneDrive será armazenamento frio

Somente snapshots, rollups, exports ou arquivos fechados serão enviados.

### ADR-003 — Battery Guard não substitui o scheduler

O macOS mantém seu gerenciamento normal.

O Battery Guard age somente com base no contexto elétrico adicional.

### ADR-004 — Foreground protegido

Aplicações ativamente usadas pelo usuário são protegidas por padrão.

### ADR-005 — Controle automático somente após aprendizado

A primeira fase é observacional.

### ADR-006 — Toda ação automática deve ser reversível e auditável

Ação, motivo e resultado serão persistidos.

---

## 28. Próximos passos imediatos

1. estabilizar `/api/system`;
2. deixar telemetria contínua funcionando;
3. iniciar medição independente do crescimento do SQLite;
4. coletar no mínimo 72 horas;
5. calcular MB/dia e GB/mês;
6. validar custo de armazenamento;
7. definir retenção;
8. somente depois implementar arquivamento remoto;
9. iniciar Behavior Engine.

---

## 29. Filosofia final do produto

O macOS otimiza o computador para que aplicações executem o trabalho solicitado pelo usuário.

O Battery Guard pretende responder a uma pergunta diferente:

> A bateria degradada consegue sustentar eletricamente a carga que o sistema deseja executar agora?

A futura proteção adaptativa usará histórico, comportamento, resposta elétrica e contexto de uso para evitar que cargas evitáveis provoquem quedas abruptas de tensão.

O objetivo não é limitar o Mac permanentemente.

O objetivo é utilizar a maior capacidade computacional possível dentro da margem elétrica que a bateria realmente consegue entregar.
