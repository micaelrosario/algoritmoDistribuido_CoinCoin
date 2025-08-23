import socket, threading, time


# Variáveis globais
saldo = 0
usuarios = {}  # Dicionário para armazenar usuários e senhas
transacoes_pendentes = {}  # Transações aguardando confirmação
transacoes_confirmadas = []  # Histórico de transações



# Configuração de sockets
socket_local = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
porta_local = 12000



# Semáforos para controle de concorrência
semaforo_usuarios = threading.BoundedSemaphore(1)
semaforo_transacoes = threading.BoundedSemaphore(1)
semaforo_saldo = threading.BoundedSemaphore(1)



# Listas para controle distribuído
hosts = set() 
concordou = set()  
neguei = set()  
critica = False  
relogio_critica = 0  
mensagem_critica = "" 
ajuste = 0  



# Obtém o IP local da máquina
def findIP():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


#Meu endereço IP
meu_ip = findIP()
print(f"IP local: {meu_ip}")


# Bind do socket
socket_local.bind((meu_ip, porta_local))
socket_local.listen(5)



def sendto(mensagem, ip):
    """Envia mensagem para outro usuário com timestamp"""
    relogio = time.time() + ajuste
    msg = f"{mensagem} {relogio}"
   
    if ip != meu_ip:
        try:
            socket_temp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_temp.connect((ip, porta_local))
            socket_temp.send(msg.encode())
            socket_temp.close()
        except:
            print(f"Erro ao enviar para {ip}")


def solicita_regiao_critica(mensagem):
    """Solicita acesso à região crítica para realizar transação"""
    global relogio_critica, mensagem_critica
    mensagem_critica = mensagem
    relogio_critica = time.time() + ajuste
   
    print("Solicitando acesso à região crítica...")
    if len(hosts) >= 1:
        for ip in hosts:
            sendto("\\request", ip)
    else:
        pass
    # se só tiver ele não precisar enviar request, apenas dar acesso a região critica      


def liberar_regiao_critica():
    """Libera a região crítica após transação"""
    global neguei, critica
    print("Liberando região crítica...")
   
    for ip in neguei:
        sendto("\\accept", ip)
    neguei.clear()
    critica = False


def processar_transacao(mensagem, origem):
    """Processa uma transação financeira"""
    global saldo, transacoes_pendentes, transacoes_confirmadas
   
    partes = mensagem.split()
    if len(partes) < 4:
        return "Formato inválido"
   
    tipo = partes[1]
    destinatario = partes[2]
   
    try:
        valor = float(partes[3])
    except ValueError:
        return "Valor inválido"
   
    if tipo == "emprestar":
        # OPERAÇÃO FINANCEIRA: Empréstimo
        semaforo_saldo.acquire()
        semaforo_transacoes.acquire()
       
        # Registrar transação pendente
        id_transacao = f"{origem}_{destinatario}_{time.time()}"
        transacoes_pendentes[id_transacao] = {
            'de': origem,
            'para': destinatario,
            'valor': valor,
            'status': 'pendente'
        }
       
        semaforo_transacoes.release()
        semaforo_saldo.release()
       
        return f"Transação de empréstimo registrada. Aguardando confirmação de {destinatario}"
   
    elif tipo == "confirmar":
        # OPERAÇÃO FINANCEIRA: Confirmação de transação
        semaforo_saldo.acquire()
        semaforo_transacoes.acquire()
       
        # Buscar transação pendente
        transacao_encontrada = None
        for id_transacao, transacao in transacoes_pendentes.items():
            if (transacao['para'] == origem and
                transacao['de'] == destinatario and
                transacao['status'] == 'pendente'):
                transacao_encontrada = transacao
                transacao_id = id_transacao
                break
       
        if transacao_encontrada:
            # Atualizar saldos
            if origem in usuarios:
                usuarios[origem]['saldo'] -= transacao_encontrada['valor']
            if destinatario in usuarios:
                usuarios[destinatario]['saldo'] += transacao_encontrada['valor']
           
            # Registrar transação confirmada
            transacoes_confirmadas.append({
                'de': transacao_encontrada['de'],
                'para': transacao_encontrada['para'],
                'valor': transacao_encontrada['valor'],
                'timestamp': time.strftime("%Y-%m-%d %H:%M:%S")
            })
           
            # Remover transação pendente
            del transacoes_pendentes[transacao_id]
           
            semaforo_transacoes.release()
            semaforo_saldo.release()
           
            return f"Transação confirmada! Saldo atualizado."
        else:
            semaforo_transacoes.release()
            semaforo_saldo.release()
            return "Transação não encontrada"
   
    return "Operação desconhecida"


#colocar enviar e receber junto
def receber():
    """Thread para receber mensagens de outros usuários"""
    global socket_local, hosts, ajuste
    global critica, relogio_critica, mensagem_critica, concordou
   
    while True:
        connection, address = socket_local.accept()
        mensagem_completa = connection.recv(256).decode()
        connection.close()
       
        if not mensagem_completa:
            continue
       
        # Separar mensagem e timestamp
        partes = mensagem_completa.rsplit(' ', 1)
        if len(partes) < 2:
            continue
           
        mensagem = partes[0]
        relogio_recebido = float(partes[1])
       
        # Sincronização de relógio lógico (Lamport)
        relogio_logico = time.time() + ajuste
        if relogio_recebido > relogio_logico:
            ajuste = relogio_recebido - time.time() + 1

        print("Chegou na função de receber")

        # Processar mensagens do sistema
        if mensagem.startswith("\\connect"):
            confirmarcao = input("Deseja confirmar conexão? SIM/NÃO\n:").upper()
            if confirmarcao == "SIM":
                sendto("\\ok", address[0])
                print("Conexão confirmada")

                semaforo_usuarios.acquire()
                hosts.add(address[0])
                semaforo_usuarios.release()

                for ip in hosts:
                    if ip != address[0]:
                        sendto(f"\\host {ip}", address[0])
                        sendto(f"\\Usuário: [{address[0]}] está conectado a rede", ip)

                print("Acessando o Sistema Financeiro...")
                time.sleep(3)
                menu_login()
            else:
                print("Negando Conexão...")
                sendto(f"Solicitação de conexão negada pelo IP {meu_ip}", address[0])
           
        elif mensagem.startswith("\\ok"):
            semaforo_usuarios.acquire()
            hosts.add(address[0])
            semaforo_usuarios.release()
           
        elif mensagem.startswith("\\request"):
           
            # Não estou usando a região crítica nem tenho interesse
            if not critica and relogio_critica == 0:
                sendto("\\accept", address[0])
            # Não estou usando a região crítica, mas quero usar e pedi depois
            elif not critica and relogio_critica > 0 and relogio_critica > relogio_recebido:
                sendto("\\accept", address[0])
            else:
                neguei.add(address[0])
               
        elif mensagem.startswith("\\accept"):
            print(f"{address[0]} concordou com a transação")
            concordou.add(address[0])
           
            # Verificar se todos concordaram
            if len(hosts - concordou) == 1:
                critica = True
                concordou.clear()
               
                # Processar a transação na região crítica
                resultado = processar_transacao(mensagem_critica, meu_ip)
                print(resultado)
               
                liberar_regiao_critica()
                print("Região crítica liberada!")
       
        # Processar mensagens de transação
        elif mensagem.startswith("\\transacao"):
            resposta = processar_transacao(mensagem, address[0])
            sendto(f"\\resposta {resposta}", address[0])

        elif mensagem.startswith("\\negado"):
            print("Encerrando sistema...")
            return False
        else:
            print(f"Mensagem desconhecida recebida de {address[0]}: {mensagem}")

def conectar_usuario(ip):
    """Conecta com outro usuário"""
    try:
        sendto("\\connect", ip)
        print(f"Tentando se conectar ao ip: {ip}")
    except:
        print(f"Erro ao conectar com {ip}")


def iniciar_conexao():
    global hosts

    print("=== INICIANDO A CONEXÃO ===\n")
    print("[ 1 ] - Iniciar como COORDENADOR")
    print("[ 2 ] - Conectar a outro nó (CLIENTE)")
    escolha = input("\nEscolha uma opção: ")

    if escolha == "1":
        menu_login()
    elif escolha == "2":
        ip = input('\nDigite o endereço ip que deseja se conectar: ')
        conectar_usuario(ip)
    else:
        print("Opção Inválida.")


def enviar_mensagem():
    """Thread para enviar mensagens"""
   
    while True:
        mensagem = input("\nDigite uma operação: ")
           
        if mensagem.startswith("\\emprestar"):
            # OPERAÇÃO FINANCEIRA: Solicitar empréstimo
            solicita_regiao_critica(mensagem)
            print(f"Solicitando empréstimo: {mensagem}")
           
        elif mensagem.startswith("\\confirmar"):
            # OPERAÇÃO FINANCEIRA: Confirmar transação
            solicita_regiao_critica(mensagem)
            print(f"Confirmando transação: {mensagem}")
           
        elif mensagem.startswith("\\saldo"):
            # Consultar saldo
            semaforo_saldo.acquire()
            if meu_ip in usuarios:
                print(f"Seu saldo: R$ {usuarios[meu_ip]['saldo']:.2f}")
            else:
                print("Usuário não encontrado")
            semaforo_saldo.release()
           
        elif mensagem.startswith("\\transacoes"):
            # Mostrar transações
            print("\n=== TRANSAÇÕES CONFIRMADAS ===")
            for transacao in transacoes_confirmadas:
                print(f"{transacao['timestamp']}: {transacao['de']} -> {transacao['para']} R$ {transacao['valor']:.2f}")
               
            print("\n=== TRANSAÇÕES PENDENTES ===")
            for id_transacao, transacao in transacoes_pendentes.items():
                print(f"Pendente: {transacao['de']} -> {transacao['para']} R$ {transacao['valor']:.2f}")
               
        elif mensagem == "\\sair":
            print("Encerrando sistema...")
            break
        else:
            print("Comando não reconhecido")


def menu_login():
    """Menu de login/cadastro de usuários"""
    global usuarios, meu_ip
   
    while True:
        print("\n" + "="*60)
        print("======= BEM VINDO AO COINCOIN - SISTEMA FINANCEIRO =======")
        print("="*60)
       
        print("\n1 - Criar novo usuário")
        print("2 - Fazer login")
        print("3 - Sair")
       
        opcao = input("\nEscolha uma opção: ")
       
        if opcao == "1":
            usuario = input('Digite um nome de usuário: ')
            senha = input('Digite a senha: ')
           
            semaforo_usuarios.acquire()
            usuarios[meu_ip] = {
                'usuario': usuario,
                'senha': senha,
                'saldo': 0.0
            }
            semaforo_usuarios.release()
           
            print('Usuário cadastrado com sucesso!')
           
        elif opcao == "2":
            usuario = input('Digite o seu usuário: ')
            senha = input('Digite a sua senha: ')
           
            semaforo_usuarios.acquire()
            usuario_encontrado = False
            for ip, dados in usuarios.items():
                if dados['usuario'] == usuario and dados['senha'] == senha:
                    usuario_encontrado = True
                    break
           
            if usuario_encontrado:
                print("Login realizado com sucesso!")
                semaforo_usuarios.release()
                return True
            else:
                print("Usuário ou senha incorretos!")
                semaforo_usuarios.release()
           
        elif opcao == "3":
            print("Encerrando sistema...")
            return False
        else:
            print("Opção inválida!")


# Inicialização do sistema
if __name__ == "__main__":
    if iniciar_conexao():
        # Iniciar threads
        t_receber = threading.Thread(target=receber, daemon=True)
        t_enviar = threading.Thread(target=enviar_mensagem)
        t_receber.start()
        t_enviar.start()
    
        t_enviar.join()