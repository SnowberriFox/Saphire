import sys


def _main() -> int:
    if "--selftest" in sys.argv[1:]:
        from sapphire import selftest
        return selftest.run()
    if "--helper" in sys.argv[1:]:
        # Headless: no Qt, so the login helper stays tiny.
        from sapphire import helper
        return helper.run()
    from sapphire.ui.app import main
    return main()


if __name__ == "__main__":
    sys.exit(_main())
