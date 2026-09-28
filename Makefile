PREFIX ?= /usr/local
DESTDIR ?=
BINDIR := $(PREFIX)/bin
LIBDIR := $(PREFIX)/lib/proton-drive-linux
DATADIR := $(PREFIX)/share
APP_ID := io.github.voxhash.ProtonDriveLinux
GETTEXT_DOMAIN := proton-drive-linux
LOCALES := en ru zh_CN ar it pt es ko ja

.PHONY: install user-install uninstall icons-cache pot update-po mo

install: mo
	install -d "$(DESTDIR)$(BINDIR)" "$(DESTDIR)$(LIBDIR)"
	install -Dm755 scripts/proton-drive-linux "$(DESTDIR)$(BINDIR)/proton-drive-linux"
	cp -a proton_drive_linux "$(DESTDIR)$(LIBDIR)/"
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
	@for lang in $(LOCALES); do \
		rm -f "$(DESTDIR)$(DATADIR)/locale/$$lang/LC_MESSAGES/$(GETTEXT_DOMAIN).mo"; \
	done

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
