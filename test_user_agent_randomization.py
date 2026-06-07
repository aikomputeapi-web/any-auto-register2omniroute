"""Test script to demonstrate User Agent randomization"""

from core.user_agent_generator import UserAgentGenerator

print("=" * 80)
print("USER AGENT RANDOMIZATION TEST")
print("=" * 80)
print()

# Generate 5 random user agents to show variety
for i in range(5):
    print(f"Sample {i+1}:")
    print("-" * 80)
    
    ua_data = UserAgentGenerator.generate()
    viewport = UserAgentGenerator.get_random_viewport()
    hardware = UserAgentGenerator.get_random_hardware()
    
    print(f"Chrome Version: {ua_data['chrome_version']}")
    print(f"User-Agent: {ua_data['user_agent']}")
    print(f"sec-ch-ua: {ua_data['sec_ch_ua']}")
    print(f"Viewport: {viewport[0]}x{viewport[1]}")
    print(f"CPU Cores: {hardware['hardware_concurrency']}")
    print(f"RAM: {hardware['device_memory']}GB")
    print()

print("=" * 80)
print("Each browser session will have a unique fingerprint!")
print("=" * 80)
