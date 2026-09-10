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
