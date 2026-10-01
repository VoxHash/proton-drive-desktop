PREFIX ?= /usr/local
DESTDIR ?=
BINDIR := $(PREFIX)/bin
LIBDIR := $(PREFIX)/lib/proton-drive-desktop
DATADIR := $(PREFIX)/share
APP_ID := io.github.voxhash.ProtonDriveDesktop
GETTEXT_DOMAIN := proton-drive-desktop
LOCALES := en ru zh_CN ar it pt es ko ja

.PHONY: install user-install uninstall user-uninstall icons-cache pot update-po mo test-offline dist appimage

install: mo
	install -d "$(DESTDIR)$(BINDIR)" "$(DESTDIR)$(LIBDIR)"
	install -Dm755 scripts/proton-drive-desktop "$(DESTDIR)$(BINDIR)/proton-drive-desktop"
	cp -a proton_drive_desktop "$(DESTDIR)$(LIBDIR)/"
	find "$(DESTDIR)$(LIBDIR)" -type d -name '__pycache__' -prune -exec rm -rf {} +
	install -Dm644 data/$(APP_ID).desktop "$(DESTDIR)$(DATADIR)/applications/$(APP_ID).desktop"
	install -Dm644 data/$(APP_ID).metainfo.xml "$(DESTDIR)$(DATADIR)/metainfo/$(APP_ID).metainfo.xml"
	install -d "$(DESTDIR)$(DATADIR)/icons"
	cp -a data/icons/hicolor "$(DESTDIR)$(DATADIR)/icons/"
	@for lang in $(LOCALES); do \
		install -d "$(DESTDIR)$(DATADIR)/locale/$$lang/LC_MESSAGES"; \
		install -Dm644 locale/$$lang/LC_MESSAGES/$(GETTEXT_DOMAIN).mo "$(DESTDIR)$(DATADIR)/locale/$$lang/LC_MESSAGES/$(GETTEXT_DOMAIN).mo"; \
	done
	-$(MAKE) icons-cache DESTDIR="$(DESTDIR)" PREFIX="$(PREFIX)"

# Rewrite Exec/TryExec to an absolute path so application menus still find the
# binary when the desktop environment's TryExec PATH omits ~/.local/bin.
user-install:
	$(MAKE) install PREFIX="$(HOME)/.local"
	@desktop="$(HOME)/.local/share/applications/$(APP_ID).desktop"; \
	bin="$(HOME)/.local/bin/proton-drive-desktop"; \
	sed -i \
		-e "s|^Exec=.*|Exec=$$bin|" \
		-e "s|^TryExec=.*|TryExec=$$bin|" \
		"$$desktop"
	-update-desktop-database "$(HOME)/.local/share/applications"
	-$(MAKE) icons-cache DESTDIR= PREFIX="$(HOME)/.local"

uninstall:
	rm -f "$(DESTDIR)$(BINDIR)/proton-drive-desktop"
	rm -rf "$(DESTDIR)$(LIBDIR)"
	rm -f "$(DESTDIR)$(DATADIR)/applications/$(APP_ID).desktop"
	rm -f "$(DESTDIR)$(DATADIR)/metainfo/$(APP_ID).metainfo.xml"
	rm -f "$(DESTDIR)$(DATADIR)/icons/hicolor/"*/apps/$(APP_ID).png
	rm -f "$(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/$(APP_ID).svg"
	@for lang in $(LOCALES); do \
		rm -f "$(DESTDIR)$(DATADIR)/locale/$$lang/LC_MESSAGES/$(GETTEXT_DOMAIN).mo"; \
	done

# Removes user-install payload under ~/.local, XDG autostart, and optional
# systemd --user sync units. Does not delete ~/.config/proton-drive-desktop or
# the official CLI (~/.local/bin/proton-drive). Use scripts/uninstall.sh --purge
# / --remove-cli for those.
user-uninstall:
	chmod +x scripts/uninstall.sh
	./scripts/uninstall.sh

icons-cache:
	-gtk-update-icon-cache -f -t "$(DESTDIR)$(DATADIR)/icons/hicolor"

pot:
	xgettext --from-code=UTF-8 --language=Python --keyword=_ --keyword=ngettext:1,2 \
		--add-comments=Translators --package-name=$(GETTEXT_DOMAIN) \
		--msgid-bugs-address=contact@voxhash.dev --copyright-holder='VoxHash Technologies' \
		--files-from=po/POTFILES.in --directory=. --output=po/$(GETTEXT_DOMAIN).pot

update-po: pot
	@for lang in $(LOCALES); do \
		msgmerge --update --backup=none po/$$lang.po po/$(GETTEXT_DOMAIN).pot; \
	done

mo:
	@for lang in $(LOCALES); do \
		install -d locale/$$lang/LC_MESSAGES; \
		msgfmt --check -o locale/$$lang/LC_MESSAGES/$(GETTEXT_DOMAIN).mo po/$$lang.po; \
	done

# Packaging smoke + unit tests without Proton API / signed-in CLI (used by CI).
test-offline: mo
	python3 scripts/run-offline-tests.py

# Source tarball + SHA256SUMS under dist/ (used by .github/workflows/release.yml).
dist:
	chmod +x scripts/build-source-tarball.sh
	./scripts/build-source-tarball.sh

# Optional AppImage (GUI only; host still needs proton-drive on PATH). Needs appimagetool (downloaded).
appimage:
	chmod +x packaging/appimage/AppRun packaging/appimage/build-appimage.sh
	./packaging/appimage/build-appimage.sh
