PREFIX ?= /usr/local
DESTDIR ?=
BINDIR := $(PREFIX)/bin
LIBDIR := $(PREFIX)/lib/proton-drive-linux
DATADIR := $(PREFIX)/share
APP_ID := io.github.voxhash.ProtonDriveLinux

.PHONY: install user-install uninstall icons-cache

install:
	install -d "$(DESTDIR)$(BINDIR)" "$(DESTDIR)$(LIBDIR)"
	install -Dm755 scripts/proton-drive-linux "$(DESTDIR)$(BINDIR)/proton-drive-linux"
	cp -a proton_drive_linux "$(DESTDIR)$(LIBDIR)/"
	find "$(DESTDIR)$(LIBDIR)" -type d -name '__pycache__' -prune -exec rm -rf {} +
	install -Dm644 data/$(APP_ID).desktop "$(DESTDIR)$(DATADIR)/applications/$(APP_ID).desktop"
	install -Dm644 data/$(APP_ID).metainfo.xml "$(DESTDIR)$(DATADIR)/metainfo/$(APP_ID).metainfo.xml"
	install -d "$(DESTDIR)$(DATADIR)/icons"
	cp -a data/icons/hicolor "$(DESTDIR)$(DATADIR)/icons/"
	-$(MAKE) icons-cache DESTDIR="$(DESTDIR)" PREFIX="$(PREFIX)"

user-install:
	$(MAKE) install PREFIX="$(HOME)/.local"
	-update-desktop-database "$(HOME)/.local/share/applications"

uninstall:
	rm -f "$(DESTDIR)$(BINDIR)/proton-drive-linux"
	rm -rf "$(DESTDIR)$(LIBDIR)"
	rm -f "$(DESTDIR)$(DATADIR)/applications/$(APP_ID).desktop"
	rm -f "$(DESTDIR)$(DATADIR)/metainfo/$(APP_ID).metainfo.xml"
	rm -f "$(DESTDIR)$(DATADIR)/icons/hicolor/"*/apps/$(APP_ID).png
	rm -f "$(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/$(APP_ID).svg"

icons-cache:
	-gtk-update-icon-cache -f -t "$(DESTDIR)$(DATADIR)/icons/hicolor"
