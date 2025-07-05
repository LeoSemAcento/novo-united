#!/usr/bin/env python3
"""
Script de demonstração das funcionalidades de descoberta automática de canais internos
"""

import asyncio
import sys
import os

# Adiciona o diretório atual ao path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from telegram_scraper import (
    normalize_id, 
    discover_internal_channels, 
    get_channel_title,
    client,
    state
)

def print_banner():
    """Exibe o banner do sistema"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║                    TELEGRAM SCRAPER v2.0                     ║
║              Descoberta Automática de Canais                 ║
╚══════════════════════════════════════════════════════════════╝
    """)

def print_menu():
    """Exibe o menu de demonstração"""
    print("""
🎯 Escolha uma opção de demonstração:

1️⃣  Testar normalização de IDs
2️⃣  Demonstrar descoberta de canais internos
3️⃣  Simular adição completa de grupos
4️⃣  Mostrar estatísticas do sistema
5️⃣  Executar todos os testes
0️⃣  Sair

Digite sua escolha: """, end="")

async def demo_normalization():
    """Demonstra a normalização de IDs"""
    print("\n🔧 DEMONSTRAÇÃO: Normalização de IDs")
    print("=" * 50)
    
    test_cases = [
        ("123456789", "ID sem prefixo"),
        ("-100123456789", "ID com prefixo"),
        ("123", "ID muito pequeno"),
        ("abc123", "ID inválido"),
        ("9876543210", "ID grande sem prefixo"),
    ]
    
    for input_id, description in test_cases:
        result = normalize_id(input_id)
        status = "✅" if result != input_id or input_id.startswith("-100") else "ℹ️"
        print(f"{status} {description:20} | {input_id:15} → {result}")

async def demo_discovery():
    """Demonstra a descoberta de canais internos"""
    print("\n🔍 DEMONSTRAÇÃO: Descoberta de Canais Internos")
    print("=" * 50)
    
    # Solicita um ID de grupo para teste
    group_id = input("Digite um ID de grupo para testar (ou Enter para usar exemplo): ").strip()
    
    if not group_id:
        group_id = "1234567890"  # ID de exemplo
        print(f"Usando ID de exemplo: {group_id}")
    
    try:
        print(f"\n🔍 Buscando canais internos para o grupo...")
        
        # Tenta obter o nome do grupo
        try:
            group_name = await get_channel_title(group_id)
            print(f"📋 Grupo: {group_name}")
        except:
            print(f"📋 Grupo ID: {group_id} (não foi possível obter o nome)")
        
        # Executa a descoberta
        discovered = await discover_internal_channels(group_id)
        
        if discovered:
            print(f"\n✅ Descoberta concluída!")
            print(f"📊 Total de canais encontrados: {len(discovered)}")
            
            for i, channel in enumerate(discovered, 1):
                print(f"  {i}. {channel['title']}")
                print(f"     ID: {channel['id']}")
        else:
            print(f"\nℹ️ Nenhum canal interno encontrado para este grupo.")
            
    except Exception as e:
        print(f"❌ Erro durante a descoberta: {e}")

async def demo_complete_addition():
    """Demonstra a adição completa de grupos"""
    print("\n➕ DEMONSTRAÇÃO: Adição Completa de Grupos")
    print("=" * 50)
    
    # Simula a entrada do usuário
    demo_input = """
    Comunidade Jon Fortuna
    2624431019
        Prompts
        6
        Regras
        2
    Outro Grupo
    9876543210
    """
    
    print("📝 Entrada simulada:")
    print(demo_input)
    
    import re
    ids = re.findall(r"\b\d{6,}\b", demo_input)
    
    print(f"🔍 IDs extraídos: {ids}")
    
    nomes_adicionados = []
    canais_internos_encontrados = []
    
    for channel_id in ids:
        test_id = normalize_id(channel_id)
        try:
            group_name = await get_channel_title(test_id)
            nomes_adicionados.append(group_name)
            print(f"✅ Adicionado grupo: {group_name} ({test_id})")
            
            # Simula descoberta de canais internos
            internal_channels = await discover_internal_channels(test_id)
            if internal_channels:
                for internal_channel in internal_channels:
                    canais_internos_encontrados.append(internal_channel['title'])
                    print(f"  ➕ Canal interno: {internal_channel['title']}")
                    
        except Exception as e:
            print(f"❌ Erro ao processar {channel_id}: {e}")
    
    print(f"\n📋 Resumo da demonstração:")
    print(f"   Grupos processados: {len(nomes_adicionados)}")
    print(f"   Canais internos encontrados: {len(canais_internos_encontrados)}")
    print(f"   Total de canais: {len(nomes_adicionados) + len(canais_internos_encontrados)}")

async def demo_statistics():
    """Mostra estatísticas do sistema"""
    print("\n📊 DEMONSTRAÇÃO: Estatísticas do Sistema")
    print("=" * 50)
    
    try:
        # Conta diálogos
        dialog_count = 0
        group_count = 0
        channel_count = 0
        
        async for dialog in client.iter_dialogs():
            dialog_count += 1
            if dialog.is_group:
                group_count += 1
            elif dialog.is_channel:
                channel_count += 1
        
        print(f"📈 Estatísticas dos diálogos:")
        print(f"   Total de diálogos: {dialog_count}")
        print(f"   Grupos: {group_count}")
        print(f"   Canais: {channel_count}")
        
        # Mostra canais salvos
        if state["channels"]:
            print(f"\n💾 Canais salvos no estado: {len(state['channels'])}")
            for channel_id in list(state["channels"].keys())[:5]:  # Mostra apenas os primeiros 5
                try:
                    name = await get_channel_title(channel_id)
                    print(f"   - {name} ({channel_id})")
                except:
                    print(f"   - ID: {channel_id}")
        else:
            print(f"\n💾 Nenhum canal salvo no estado")
            
    except Exception as e:
        print(f"❌ Erro ao obter estatísticas: {e}")

async def run_all_tests():
    """Executa todos os testes"""
    print("\n🚀 EXECUTANDO TODOS OS TESTES")
    print("=" * 50)
    
    await demo_normalization()
    await demo_discovery()
    await demo_complete_addition()
    await demo_statistics()
    
    print("\n✅ Todos os testes concluídos com sucesso!")

async def main():
    """Função principal"""
    print_banner()
    
    # Inicia o cliente
    await client.start()
    
    try:
        while True:
            print_menu()
            choice = input().strip()
            
            if choice == "1":
                await demo_normalization()
            elif choice == "2":
                await demo_discovery()
            elif choice == "3":
                await demo_complete_addition()
            elif choice == "4":
                await demo_statistics()
            elif choice == "5":
                await run_all_tests()
            elif choice == "0":
                print("\n👋 Saindo da demonstração...")
                break
            else:
                print("❌ Opção inválida. Tente novamente.")
            
            input("\nPressione Enter para continuar...")
            print("\n" + "="*60 + "\n")
            
    except KeyboardInterrupt:
        print("\n\n👋 Demonstração interrompida pelo usuário.")
    except Exception as e:
        print(f"\n❌ Erro durante a demonstração: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main()) 