def validate_ssh_port(value:int|str)-> int:
    """Validates the SSH Port and returns if the input port is valid

    Args:
        value (int): expected input values is int , try typecasting into int if not possible raise ValueError

    Returns:
        int: return value as integer if it is valid port number
    """
    if isinstance(value, (bool, float)):
        raise ValueError("Port cannot be a boolean value")

    try:
        port = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Port must be valid integer, got {value!r}")

    if not (1 <= port <= 65535):
        raise ValueError(f"Port must be between 1 and 65535, got {port}")

    return port

if __name__ == "__main__":
    print(validate_ssh_port(22))      # Should return 22
    print(validate_ssh_port("22"))    # Should return 22
