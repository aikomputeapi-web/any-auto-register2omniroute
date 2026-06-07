"""User Agent randomization for stealth browsing"""

import random
from typing import Dict, Tuple


class UserAgentGenerator:
    """Generates realistic Chrome user agents with matching client hints"""
    
    # Recent Chrome versions (last 6 months)
    CHROME_VERSIONS = [
        "131.0.0.0",
        "130.0.0.0", 
        "129.0.0.0",
        "128.0.0.0",
        "127.0.0.0",
        "126.0.0.0",
    ]
    
    # Windows versions
    WINDOWS_VERSIONS = [
        "10.0",  # Windows 10/11
    ]
    
    # Platform versions for sec-ch-ua-platform-version
    PLATFORM_VERSIONS = [
        "10.0.0",
        "15.0.0",
    ]
    
    @staticmethod
    def generate() -> Dict[str, str]:
        """
        Generate a random user agent with matching client hints
        
        Returns:
            Dict with 'user_agent', 'sec_ch_ua', 'sec_ch_ua_full_version_list', 
            'sec_ch_ua_platform_version', and 'chrome_version'
        """
        chrome_version = random.choice(UserAgentGenerator.CHROME_VERSIONS)
        windows_version = random.choice(UserAgentGenerator.WINDOWS_VERSIONS)
        platform_version = random.choice(UserAgentGenerator.PLATFORM_VERSIONS)
        
        # Extract major version
        major_version = chrome_version.split('.')[0]
        
        # Build user agent
        user_agent = (
            f"Mozilla/5.0 (Windows NT {windows_version}; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome_version} Safari/537.36"
        )
        
        # Build sec-ch-ua (client hints)
        sec_ch_ua = (
            f'"Google Chrome";v="{major_version}", '
            f'"Chromium";v="{major_version}", '
            f'"Not_A Brand";v="24"'
        )
        
        # Build sec-ch-ua-full-version-list
        sec_ch_ua_full_version_list = (
            f'"Google Chrome";v="{chrome_version}", '
            f'"Chromium";v="{chrome_version}", '
            f'"Not_A Brand";v="24.0.0.0"'
        )
        
        return {
            "user_agent": user_agent,
            "sec_ch_ua": sec_ch_ua,
            "sec_ch_ua_full_version_list": sec_ch_ua_full_version_list,
            "sec_ch_ua_platform_version": platform_version,
            "chrome_version": chrome_version,
            "major_version": major_version,
        }
    
    @staticmethod
    def get_viewport_for_resolution(resolution: str) -> Tuple[int, int]:
        """
        Get viewport dimensions for common screen resolutions
        
        Args:
            resolution: One of '1920x1080', '1366x768', '1536x864', '1440x900'
            
        Returns:
            Tuple of (width, height)
        """
        resolutions = {
            "1920x1080": (1920, 1080),
            "1366x768": (1366, 768),
            "1536x864": (1536, 864),
            "1440x900": (1440, 900),
            "1280x720": (1280, 720),
            "1600x900": (1600, 900),
        }
        return resolutions.get(resolution, (1920, 1080))
    
    @staticmethod
    def get_random_viewport() -> Tuple[int, int]:
        """Get a random viewport from common resolutions"""
        resolutions = [
            (1920, 1080),  # Most common
            (1366, 768),   # Second most common
            (1536, 864),   # Common laptop
            (1440, 900),   # MacBook-like
            (1280, 720),   # HD
            (1600, 900),   # 16:9
        ]
        # Weight towards more common resolutions
        weights = [40, 25, 15, 10, 5, 5]
        return random.choices(resolutions, weights=weights)[0]
    
    @staticmethod
    def get_random_hardware() -> Dict[str, int]:
        """Get random but realistic hardware specs"""
        cores_options = [4, 6, 8, 12, 16]
        memory_options = [4, 8, 16, 32]
        
        # Weight towards more common configurations
        cores = random.choices(cores_options, weights=[10, 20, 40, 20, 10])[0]
        memory = random.choices(memory_options, weights=[5, 50, 35, 10])[0]
        
        return {
            "hardware_concurrency": cores,
            "device_memory": memory,
        }
