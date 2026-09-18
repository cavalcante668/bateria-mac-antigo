# MacBook Battery Guard

Ferramenta local de monitoramento de bateria para macOS criada para
acompanhar, em tempo real, o comportamento das células de uma bateria
de MacBook.

O projeto surgiu da necessidade de monitorar uma bateria cujo percentual
informado pelo BMS/macOS não representa adequadamente a autonomia real.

O sistema acompanha diretamente dados expostos pelo
`AppleSmartBattery`, permitindo observar tensão individual das células,
diferença de tensão entre elas, corrente, potência, capacidade reportada
e comportamento da bateria sob carga.

## Componentes

### Battery Guard

`battery-guard.sh`

Monitor leve executado em background.

Monitora principalmente:

- tensão das células;
- menor tensão observada;
- diferença entre maior e menor célula;
- estado do carregador;
- condições operacionais de alerta.

Pode emitir:

- notificação do macOS;
- alerta sonoro;
- aviso por voz;
- registro em log.

### Battery View

`battery-view.py`

Dashboard web local disponível por padrão em:

```text
http://127.0.0.1:8765

---

## Histórico de versões

### Primeira versão — monitoramento e dashboard

A primeira versão do Battery Guard estabeleceu a base de monitoramento da bateria no macOS.

Principais recursos:

- leitura das tensões individuais das células;
- cálculo da menor tensão e do DELTA entre as células;
- leitura de corrente, potência, temperatura e percentual informado pelo BMS;
- identificação de alimentação externa e carregamento;
- armazenamento histórico das medições;
- dashboard web local em tempo real;
- registro das sessões em bateria e alimentação externa;
- monitoramento dos processos com maior consumo.

### Indicadores empíricos de risco

Commit de referência: `26bd047` — Add portable macOS support and empirical battery risk indicators.

Nessa etapa foram adicionados indicadores destinados a complementar as informações fornecidas pelo BMS:

- energia útil estimada;
- risco de desligamento;
- projeção da célula sob carga;
- avaliação do desequilíbrio entre células;
- classificação em SEGURO, ATENÇÃO, ALERTA e CRÍTICO;
- estrutura portátil para execução em outros Macs.

### Interface nativa para macOS

Commit de referência: `2af3092` — Add native macOS interface and Battery Guard branding.

O Battery Guard passou a funcionar como aplicativo nativo do macOS, sem depender da abertura manual do navegador.

Foram implementados:

- janela nativa com pywebview;
- aplicativo `.app`;
- identidade visual Battery Guard;
- ícone próprio;
- integração com AppKit;
- bundle `com.batteryguard.app`;
- build com PyInstaller.

### Neutralização dos identificadores

Commit de referência: `5e946f5` — Neutralize project service identifiers.

Os identificadores específicos da máquina de desenvolvimento foram removidos do projeto versionado.

Os serviços passaram a utilizar identificadores neutros:

- `com.batteryguard.guard`;
- `com.batteryguard.view`;
- `com.batteryguard.processresolver`;
- `com.batteryguard.app`.

### Tooltips e ajuda integrada

Commit de referência: `29198a9` — Add dashboard help tooltips and neutralize identifiers.

Foram adicionados indicadores de ajuda aos cartões do dashboard, com explicações das métricas exibidas.

Também foram neutralizadas as descrições de C1, C2 e C3 para permitir o uso do aplicativo em diferentes baterias.

### Versão 0.3.0 — integração com o macOS

Nesta versão o Battery Guard passou a funcionar de forma mais integrada ao sistema operacional.

Principais alterações:

- ícone dinâmico conforme o estado da bateria;
- variantes verde, amarela e vermelha do indicador;
- integração com a barra de menus do macOS;
- menu compacto com status, C1, C2, C3, DELTA e risco;
- atualização dos dados através da API interna;
- suporte a execução em segundo plano;
- janela principal iniciada de forma oculta;
- opção Abrir Battery Guard na barra superior;
- opção Sair para encerramento real do processo;
- modo Accessory para remover o aplicativo do Dock e do Command+Tab;
- correção das operações AppKit para execução na main thread.

### Estados visuais

- SEGURO: verde;
- ATENÇÃO: amarelo;
- ALERTA: alternância entre amarelo e vermelho;
- CRÍTICO: vermelho.

Dashboard, Dock e barra superior utilizam a mesma classificação calculada pelo Battery Guard.

### Arquitetura atual

`Coleta da bateria -> Histórico/API -> Dashboard/Menu Bar/Janela nativa`

### Próximas etapas

- inicialização automática com o macOS;
- opção gráfica para ativar ou desativar a inicialização automática;
- modo de simulação de estados;
- validação em Apple Silicon;
- build arm64 ou Universal 2;
- generalização do modelo empírico para diferentes baterias;
- publicação de builds através de Releases do GitHub.

## Histórico de commits

Para consultar a evolução completa do código:

```bash
git log --oneline --decorate --reverse
```
