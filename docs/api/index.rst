:orphan:

..
   Hosts the recursive autosummary entry point that (re)generates
   docs/api/generated/*. Marked :orphan: because the visible navigation reaches
   the generated stubs directly from index.md's toctree (api/generated/
   stratified_packager), so this page never appears in the sidebar -- which also
   keeps the build warning-free under sphinx-build -W. Lives in a .rst file (not
   index.md) so the autosummary directive needs no eval-rst.

API Reference
=============

.. autosummary::
   :toctree: generated
   :recursive:

   stratified_packager
