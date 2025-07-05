#!/usr/bin/env python3
"""
Script de teste para as funcionalidades de descoberta automática de canais internos
"""

import asyncio
import sys
import os

# Adiciona o diretório atual ao path para importar as funções
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from telegram_scraper import (
    normalize_id, 
    discover_internal_channels, 
    get_channel_title,
    client,
    state
)

async def test_normalize_id():
    """Testa a função de normalização de IDs"""
    print("🧪 Testando normalização de IDs...")
    
    test_cases = [
        ("123456789", "-100123456789"),
        ("-100123456789", "-100123456789"),
        ("123", "123"),  # Muito pequeno
        ("abc123", "abc123"),  # Não numérico
    ]
    
    for input_id, expected in test_cases:
        result = normalize_id(input_id)
        status = "✅" if result == expected else "❌"
        print(f"  {status} {input_id} -> {result} (esperado: {expected})")

async def test_discovery():
    """Testa a descoberta de canais internos"""
    print("\n🔍 Testando descoberta de canais internos...")
    
    # Testa com um ID de grupo conhecido (substitua por um ID real)
    test_group_id = "1234567890"  # Substitua por um ID real do seu grupo
    
    try:
        # Primeiro verifica se o grupo existe
        group_name = await get_channel_title(test_group_id)
        print(f"  📋 Grupo de teste: {group_name}")
        
        # Testa a descoberta
        discovered = await discover_internal_channels(test_group_id)
        
        if discovered:
            print(f"  ✅ Encontrados {len(discovered)} canais internos:")
            for channel in discovered:
                print(f"     - {channel['title']} (ID: {channel['id']})")
        else:
            print("  ℹ️ Nenhum canal interno encontrado")
            
    except Exception as e:
        print(f"  ❌ Erro no teste: {e}")

async def test_integration():
    """Testa a integração completa"""
    print("\n🔧 Testando integração completa...")
    
    # Simula a adição de um grupo com descoberta automática
    test_input = "1234567890, 9876543210"  # IDs de exemplo
    
    import re
    ids = re.findall(r"\b\d{6,}\b", test_input)
    
    print(f"  📝 IDs extraídos: {ids}")
    
    for channel_id in ids:
        normalized_id = normalize_id(channel_id)
        print(f"  🔄 ID normalizado: {channel_id} -> {normalized_id}")

async def main():
    """Função principal de teste"""
    print("🚀 Iniciando testes das funcionalidades de descoberta...")
    
    # Inicia o cliente
    await client.start()
    
    try:
        await test_normalize_id()
        await test_discovery()
        await test_integration()
        
        print("\n✅ Todos os testes concluídos!")
        
    except Exception as e:
        print(f"\n❌ Erro durante os testes: {e}")
    
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main()) 