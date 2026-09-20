# Sistema de Notificações — Battery Guard

Atualizado em: 20/09/2026

## Visão geral

O Battery Guard possui um sistema próprio de notificações integrado à aplicação.

As notificações podem ser apresentadas em:

- Central de Notificações dentro da interface principal;
- badge de notificações não lidas no Dock;
- contador no menu do Battery Guard;
- notificação nativa do macOS, quando aplicável.

A interface principal possui as abas:

- Bateria
- Sistema
- Notificações

A aba `Notificações` utiliza o mesmo armazenamento e contador usados pelo Dock e pelo menu nativo.

## Componentes

### `portable/app/battery_notifications.py`

Responsável pelo armazenamento e gerenciamento das notificações.

Principais responsabilidades:

- criação de notificações;
- leitura do histórico;
- contador de não lidas;
- marcação individual como lida;
- marcação de todas como lidas;
- limpeza do histórico;
- controle de repetição;
- persistência atômica em JSON;
- disparo de notificações nativas.

Os dados ficam em:

    ~/Library/Application Support/Battery Guard/notifications/

Arquivos principais:

    notifications.json
    notifications.lock
    monitor-state.json

### `portable/app/notification-monitor.py`

Worker responsável pelo monitoramento contínuo.

Worker no launcher:

    alerts

Monitora:

- novos erros nos logs;
- espaço livre em disco;
- duplicidade de eventos;
- cooldown de alertas repetidos.

O monitor começa a acompanhar os logs a partir do EOF para evitar alertas referentes a erros históricos.

### `portable/app/notification-center.py`

Central de Notificações em janela independente.

Ela permanece disponível pelo menu nativo mesmo com a Central integrada à janela principal.

## Integração em `battery-view.py`

A interface principal contém a aba:

    🔔 Notificações

APIs internas:

    GET  /api/notifications
    POST /api/notifications/read
    POST /api/notifications/read-all
    POST /api/notifications/clear

A interface permite:

- visualizar notificações em ordem cronológica;
- identificar notificações não lidas;
- marcar uma notificação como lida;
- marcar todas como lidas;
- limpar o histórico;
- visualizar quantidade de notificações não lidas.

## Análise da C1

Quando o usuário solicita `Analisar histórico`, a interface chama:

    analysis --json --notify

A notificação somente é criada quando essa análise termina com sucesso.

Título:

    Battery Guard — Análise da C1 concluída

Mensagem:

    A análise do comportamento dos aplicativos durante o uso elevado da C1 está pronta para consulta.

Execuções técnicas sem `--notify`, como:

    battery-analysis.py --json

não geram a notificação.

## Monitoramento de erros

São observadas ocorrências contendo termos como:

    ERROR
    ERRO
    FATAL
    Traceback
    Exception
    Failed
    Failure

Eventos idênticos possuem cooldown de 10 minutos.

Ocorrências repetidas dentro desse intervalo incrementam `repeat_count` em vez de criar notificações sucessivas.

## Espaço em disco

Limites atuais:

    Normal:   acima de 15 GiB livres
    Aviso:    15 GiB ou menos
    Crítico:  8 GiB ou menos

Verificação:

    60 segundos

Intervalos aproximados de repetição:

    Aviso:    6 horas
    Crítico:  1 hora

## Launcher

Workers atualmente utilizados:

    view
    resolver
    analysis
    native
    alerts
    notifications

`alerts` é iniciado automaticamente.

`notifications` abre a Central de Notificações independente.

## Badge e menu nativo

O `native-view.py` acompanha a quantidade de notificações não lidas.

O contador pode ser refletido em:

- Dock;
- menu do Battery Guard;
- aba Notificações da interface principal.

Exemplo:

    🔔 Notificações 🔴 3

## Logs

Logs relacionados ao sistema:

    ~/Library/Application Support/Battery Guard/logs/notifications.log
    ~/Library/Application Support/Battery Guard/logs/notification-monitor.log

## Build

Ambiente de build:

    portable/build/venv-native

Componentes presentes nesse ambiente:

- Python 3.14;
- PyInstaller;
- pywebview;
- PyObjC.

Spec utilizado:

    portable/build/BatteryGuardNative.spec

O spec inclui toda a pasta:

    portable/app

portanto os módulos do sistema de notificações são incorporados ao `.app`.

## Interface e porta 8765

A interface interna utiliza:

    http://127.0.0.1:8765

Durante a implementação foi identificado um servidor legado executando:

    ~/Scripts/battery-view.py

Esse processo permanecia ativo e ocupava a porta 8765.

Como consequência, o `.app` novo era iniciado corretamente, mas sua janela carregava a interface antiga fornecida pelo processo legado.

O fluxo antigo foi desativado.

Quando o Battery Guard empacotado estiver ativo, não deve existir um processo independente semelhante a:

    Python ~/Scripts/battery-view.py

## Backups `.app` e Launchpad

Versões antigas estavam armazenadas em:

    ~/Applications/Battery Guard Backups/

Como aplicativos localizados em `~/Applications` podem ser indexados pelo Launchpad, versões como:

    Battery Guard.previous.app

voltaram a aparecer no Launchpad e chegaram a ser executadas.

Os backups foram movidos para fora de `~/Applications`.

Backups futuros também devem permanecer fora desse diretório.

## Arquitetura resumida

    Battery Guard
        |
        +-- launcher.py
        |     +-- view
        |     +-- resolver
        |     +-- analysis
        |     +-- native
        |     +-- alerts
        |     +-- notifications
        |
        +-- battery-view.py
        |     +-- Bateria
        |     +-- Sistema
        |     +-- Notificações
        |
        +-- battery_notifications.py
        |
        +-- notification-monitor.py
        |
        +-- notification-center.py
        |
        +-- native-view.py
              +-- menu
              +-- Dock badge
