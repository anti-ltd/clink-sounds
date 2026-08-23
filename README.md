<p align="center">
  <img src="https://raw.githubusercontent.com/anti-ltd/clink-language-packs/main/icon-1024.png" width="96" alt="Clink app icon">
</p>

<h1 align="center">Clink sounds</h1>

<p align="center">Open key-sound packs for Clink.</p>

This repository is where people can publish short, conditioned key-click packs for Clink. Packs are ordinary `.clinkpack` files containing metadata and WAV samples; they are data only and cannot run code in Clink.

## Official Clink repositories

[Language packs](https://github.com/anti-ltd/clink-language-packs) · [Layouts](https://github.com/anti-ltd/clink-layouts) · [Profiles](https://github.com/anti-ltd/clink-profiles) · [Themes](https://github.com/anti-ltd/clink-themes) · [Panels](https://github.com/anti-ltd/clink-panels) · [Actions](https://github.com/anti-ltd/clink-actions) · [Fonts](https://github.com/anti-ltd/clink-fonts) · [Sounds](https://github.com/anti-ltd/clink-sounds)

## Included sounds

The official repository currently includes:

- **Clicky Blue** — sharp, springy click with a crisp tail
- **Tactile Brown** — deep, rounded thock of a lubed brown switch
- **Typewriter** — mechanical hammer strike and carriage ring
- **Marble** — soft, glassy tap for an understated sound

Each pack is published as a verified `.clinkpack` release asset under [`Sounds/`](Sounds).

## Make your first sound pack

1. Open Clink and go to **Customize → Feel**.
2. Create a custom sound pack and record or import up to four short sounds.
3. Export the pack as a `.clinkpack` file.
4. Put the exported file inside this repository's `Sounds` folder.
5. Push your changes to `main`.

The included GitHub workflow calculates the SHA-256 hash and byte count, builds `manifest.json`, and publishes the pack in the `latest` release. You do not need to create the manifest or release by hand.

A sound pack contains the pack metadata and conditioned mono 44.1 kHz WAV samples. Clink limits each sample to 0.5 seconds and each pack to four samples so the keyboard extension stays small and responsive.

## Add your repository to Clink

The official repository is available automatically under **Customize → Feel → Sound**. For a community repository, open **General → Repositories**, add `owner/repository`, then return to the sound source tabs and choose it.

Clink downloads only public HTTPS GitHub release assets from the repository named in the manifest. It verifies the manifest, file size, SHA-256 hash, pack metadata, sample names, and WAV headers before copying the samples into the shared keyboard container.

## Licensing

Only publish sounds you created or have permission to redistribute. Add any attribution and licence information to this README or the pack description before publishing.
